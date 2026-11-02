import sys
from pathlib import Path

from sdd_pilot import config
from sdd_pilot.brief import build_brief, signatures
from sdd_pilot.check import (
    StepResult,
    format_report,
    resolve_cmd,
    run_all,
    run_step,
    scan_wording,
    signature,
)
from sdd_pilot.config import CheckStep, Wording

PY = sys.executable

# --- check steps --------------------------------------------------------------


def test_passing_and_failing_steps(repo: Path) -> None:
    ok = run_step(repo, CheckStep("ok", (PY, "-c", "print('fine')")))
    bad = run_step(
        repo,
        CheckStep("bad", (PY, "-c", "print('x.py:3:1: E1 bad'); raise SystemExit(1)"), r":\d+:"),
    )
    assert ok.ok and ok.detail == ()
    assert not bad.ok and bad.detail == ("x.py:3:1: E1 bad",)


def test_failing_step_without_keep_shows_tail(repo: Path) -> None:
    result = run_step(repo, CheckStep("t", (PY, "-c", "print('a');print('b');exit(2)")))
    assert result.detail == ("a", "b")


def test_coverage_line_kept_on_success(repo: Path) -> None:
    result = run_step(repo, CheckStep("t", (PY, "-c", "print('TOTAL   10  1   90%')")))
    assert result.ok and result.detail == ("TOTAL   10  1   90%",)


def test_missing_command_is_a_failure_not_a_crash(repo: Path) -> None:
    result = run_step(repo, CheckStep("t", ("definitely-not-a-command-xyz",)))
    assert not result.ok and "command not found" in result.detail[0]


def test_resolve_prefers_project_relative_path(repo: Path) -> None:
    (repo / "tool.sh").write_text("")
    assert resolve_cmd(("tool.sh", "-x"), repo) == [str(repo / "tool.sh"), "-x"]


def test_run_all_uses_config(repo: Path) -> None:
    raw = {"check": [{"name": "t", "cmd": [PY, "-c", "pass"]}], "wording": {"banned": []}}
    results = run_all(config.from_dict(repo, raw))
    assert [r.name for r in results] == ["t", "wording"] and all(r.ok for r in results)


# --- wording ------------------------------------------------------------------


def _wording(**kwargs: object) -> Wording:
    return Wording(banned=("failure predicted", r"\bhealthy\b"), **kwargs)  # type: ignore[arg-type]


def test_wording_flags_overclaims_allows_negation_and_marker(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text(
        '"""Rows are unknown, never healthy."""\nMSG = "failure predicted"\n'
        'OK = "healthy"  # sdd: allow-wording\nBAD = "the unit is healthy"\n'
    )
    result = scan_wording(tmp_path, _wording())
    assert not result.ok
    assert result.detail == (
        'src/a.py:2: MSG = "failure predicted"',
        'src/a.py:4: BAD = "the unit is healthy"',
    )


def test_wording_skips_vendored_dirs_and_unscanned_suffixes(tmp_path: Path) -> None:
    (tmp_path / "src" / "node_modules").mkdir(parents=True)
    (tmp_path / "src" / "node_modules" / "x.js").write_text("failure predicted")
    (tmp_path / "src" / "data.csv").write_text("failure predicted")
    assert scan_wording(tmp_path, _wording()).ok


def test_wording_off_when_nothing_banned(tmp_path: Path) -> None:
    assert scan_wording(tmp_path, Wording()).ok


# --- signature and report ---------------------------------------------------------


def test_signature_ignores_line_numbers_and_timings() -> None:
    a = [StepResult("types", False, ("src/x.py:10: error: bad", "1 failed in 0.52s"))]
    b = [StepResult("types", False, ("src/x.py:12: error: bad", "1 failed in 3.1s"))]
    c = [StepResult("types", False, ("src/x.py:12: error: other",))]
    assert signature(a) == signature(b) != signature(c)
    assert signature([StepResult("lint", True, ())]) == ""


def test_report_is_compact() -> None:
    results = [
        StepResult("lint", True, ()),
        StepResult("tests", False, ("FAILED tests/t.py::test_x", "TOTAL 100 5 95%")),
    ]
    report = format_report(results).splitlines()
    assert report[0] == "SDD CHECK: FAIL (lint ok, tests FAIL)"
    assert "coverage: TOTAL 100 5 95%" in report
    assert "FAILED tests/t.py::test_x" in report
    assert report[-1].startswith("SIGNATURE: ")


def test_report_without_steps() -> None:
    assert format_report([]) == "SDD CHECK: PASS (no steps configured)"


# --- brief ----------------------------------------------------------------------


def test_brief_contains_only_relevant_context(repo: Path, cfg: config.Config) -> None:
    brief = build_brief(cfg, repo / "specs" / "009-demo", ["T-009-02"], sdd="bash .sdd/bin/sdd")
    assert "T-009-02" in brief and "T-009-04" not in brief
    assert "make_demo(df)" in brief and "unrelated line" not in brief
    assert "REQ-009-01" in brief and "AC-01" in brief
    assert "### src/demo/demo.py\n(new file)" in brief
    assert "`bash .sdd/bin/sdd check`" in brief
    assert "STATUS: done | blocked" in brief


def test_brief_shows_sibling_modules_for_new_files(repo: Path, cfg: config.Config) -> None:
    package = repo / "src" / "demo"
    package.mkdir(parents=True)
    (package / "config.py").write_text("class DemoConfig: ...\n")
    brief = build_brief(cfg, repo / "specs" / "009-demo", ["T-009-02"])
    assert "### src/demo/config.py\nclass DemoConfig" in brief


def test_brief_rejects_unknown_task(repo: Path, cfg: config.Config) -> None:
    import pytest

    with pytest.raises(ValueError, match="unknown"):
        build_brief(cfg, repo / "specs" / "009-demo", ["T-009-42"])


def test_python_signatures(tmp_path: Path) -> None:
    module = tmp_path / "m.py"
    module.write_text(
        'def f(a: int) -> int:\n    """Add one."""\n    return a + 1\n\n'
        "def _hidden() -> None: ...\n\nclass C: ...\n"
    )
    assert signatures(module) == ["def f(a: int) -> int  # Add one.", "class C"]


def test_typescript_signatures(tmp_path: Path) -> None:
    module = tmp_path / "m.ts"
    module.write_text(
        "export function add(a: number): number {\n  return a + 1\n}\n"
        "const hidden = 1\nexport interface Thing {\n}\n"
    )
    assert signatures(module) == [
        "export function add(a: number): number",
        "export interface Thing",
    ]


def test_brief_matches_dotted_name_to_file_in_plan(repo: Path, cfg: config.Config) -> None:
    (repo / "specs" / "009-demo" / "plan.md").write_text(
        "| `src/hello.py` | builds the greeting |\n| `src/other.py` | unrelated |\n"
    )
    tasks = repo / "specs" / "009-demo" / "tasks.md"
    tasks.write_text(
        "| ID | Task | Test | Risk | Status |\n|---|---|---|---|---|\n"
        "| T-009-01 | `hello.greet` returns it | works | low | [ ] |\n"
    )
    brief = build_brief(cfg, repo / "specs" / "009-demo", ["T-009-01"])
    assert "builds the greeting" in brief and "unrelated" not in brief
