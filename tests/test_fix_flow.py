"""The bug-fix flow: fix templates, analyze checks and fix/ branches."""

import subprocess
from pathlib import Path

import pytest

from specsteward import config
from specsteward import state as run_state
from specsteward.analyze import HIGH, analyze
from specsteward.init import TEMPLATES, init_project

FIX_SPEC = """\
# Spec 012: Fix crash on empty input
- **Status:** Draft
- **Kind:** fix
## Reproduction
1. Run `tool --input ""`.
## Expected
A usage message.
## Actual
`IndexError: list index out of range`
## Requirements
- REQ-012-01: The reproduction above no longer fails, proven by a regression test.
## Acceptance criteria
- [ ] AC-1: The regression test fails before the fix and passes after it.
"""
FIX_PLAN = "| `src/tool.py` | guard empty input |\n"
FIX_TASKS = """\
| ID | Task | Test | Risk | Status |
|---|---|---|---|---|
| T-012-01 | Regression test for empty input (REQ-012-01) | fails first | high | [ ] |
| T-012-02 | `src/tool.py` guard (REQ-012-01) | passes | high | [ ] |
"""


def _fix(tmp_path: Path, spec: str = FIX_SPEC, tasks: str = FIX_TASKS) -> Path:
    spec_dir = tmp_path / "specs" / "012-fix-empty-input"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(spec)
    (spec_dir / "plan.md").write_text(FIX_PLAN)
    (spec_dir / "tasks.md").write_text(tasks)
    return spec_dir


def _high(spec_dir: Path) -> list[str]:
    return [f.message for f in analyze(spec_dir) if f.level == HIGH]


def test_a_complete_fix_spec_is_clean(tmp_path: Path) -> None:
    assert analyze(_fix(tmp_path)) == []


def test_fix_spec_needs_reproduction_steps(tmp_path: Path) -> None:
    spec = FIX_SPEC.replace('1. Run `tool --input ""`.', "<!-- steps -->\n1.")
    assert "fix spec without reproduction steps" in _high(_fix(tmp_path, spec=spec))


def test_fix_starts_with_a_regression_test(tmp_path: Path) -> None:
    tasks = FIX_TASKS.replace("Regression test for empty input", "Write a test")
    assert "a fix starts with a failing regression test task" in _high(_fix(tmp_path, tasks=tasks))


def test_feature_specs_are_not_held_to_fix_rules(tmp_path: Path) -> None:
    spec = FIX_SPEC.replace("- **Kind:** fix\n", "").replace("## Reproduction\n", "## Notes\n")
    tasks = FIX_TASKS.replace("Regression test for empty input", "Write a test")
    assert _high(_fix(tmp_path, spec=spec, tasks=tasks)) == []


def test_untouched_fix_template_is_blocked(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "013-fix-x"
    spec_dir.mkdir(parents=True)
    for name in ("spec.md", "plan.md", "tasks.md"):
        (spec_dir / name).write_text((TEMPLATES / "fix" / name).read_text(encoding="utf-8"))
    levels = {f.level for f in analyze(spec_dir)}
    assert "CRITICAL" in levels  # placeholders such as <short description> remain


def test_init_writes_the_fix_templates(tmp_path: Path) -> None:
    init_project(tmp_path, "generic")
    for name in ("spec.md", "plan.md", "tasks.md"):
        assert (tmp_path / "specs" / "_template_fix" / name).is_file()


@pytest.mark.parametrize(
    ("branch", "ok"), [("fix/009-crash", True), ("feature/009-x", True), ("main", False)]
)
def test_start_accepts_fix_branches(repo: Path, cfg: config.Config, branch: str, ok: bool) -> None:
    for args in (["init", "-q"], ["checkout", "-q", "-b", branch]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    if ok:
        assert run_state.start(cfg, "009")["active"] is True
    else:
        with pytest.raises(ValueError, match="fix/009-"):
            run_state.start(cfg, "009")
