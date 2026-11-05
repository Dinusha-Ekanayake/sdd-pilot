from pathlib import Path

import pytest

from specsteward import config
from specsteward.__main__ import main
from specsteward.analyze import CRITICAL, HIGH, LOW, MEDIUM, analyze, format_findings
from specsteward.brief import build_brief
from specsteward.init import init_project

SPEC = """\
# Spec 010: limiter
- **Status:** Draft
## Requirements
- REQ-010-01: Allow 10 requests per second per key.
- REQ-010-02: Reject requests over the limit with HTTP 429.
## Acceptance criteria
- [ ] AC-1: 11th request in a second gets 429.
"""
PLAN = "| `src/limiter.py` | token bucket |\n"
TASKS = """\
| ID | Task | Test | Risk | Status |
|---|---|---|---|---|
| T-010-01 | `src/limiter.py` bucket (REQ-010-01) | refill | high | [ ] |
| T-010-02 | 429 response (REQ-010-02) | over limit | low | [ ] |
"""


def _spec(tmp_path: Path, spec: str = SPEC, plan: str = PLAN, tasks: str = TASKS) -> Path:
    spec_dir = tmp_path / "specs" / "010-limiter"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(spec)
    (spec_dir / "plan.md").write_text(plan)
    (spec_dir / "tasks.md").write_text(tasks)
    return spec_dir


def _messages(spec_dir: Path, level: str) -> list[str]:
    return [f.message for f in analyze(spec_dir) if f.level == level]


def test_a_complete_spec_is_clean(tmp_path: Path) -> None:
    spec_dir = _spec(tmp_path)
    assert analyze(spec_dir) == []
    assert format_findings(spec_dir, []).endswith("OK (0 critical, 0 high, 0 medium)")


def test_unresolved_clarification_and_placeholders_block(tmp_path: Path) -> None:
    spec = SPEC.replace("10 requests", "[NEEDS CLARIFICATION: how many? (a) 10 (b) 100]")
    spec_dir = _spec(tmp_path, spec=spec + "- **Branch:** `feature/<NNN>-x`\nTBD later\n")
    assert _messages(spec_dir, CRITICAL) == [
        "unresolved clarification",
        "template placeholder left",
        "template placeholder left",
    ]
    assert "BLOCKED" in format_findings(spec_dir, analyze(spec_dir))


def test_guidance_comments_and_todo_apps_are_not_flagged(tmp_path: Path) -> None:
    spec = SPEC + "<!-- Unsure? Write [NEEDS CLARIFICATION: question]. -->\n"
    spec = spec.replace("per key", "per key in the TODO app")
    assert _messages(_spec(tmp_path, spec=spec), CRITICAL) == []


def test_coverage_both_ways(tmp_path: Path) -> None:
    tasks = TASKS.replace("(REQ-010-02)", "(REQ-010-09)")
    spec_dir = _spec(tmp_path, tasks=tasks)
    assert _messages(spec_dir, HIGH) == [
        "REQ-010-09 is cited but not defined in spec.md",
        "REQ-010-02 has no task",
    ]


def test_tasks_without_any_citation_get_one_hint(tmp_path: Path) -> None:
    tasks = TASKS.replace(" (REQ-010-01)", "").replace(" (REQ-010-02)", "")
    assert _messages(_spec(tmp_path, tasks=tasks), MEDIUM) == [
        "no task cites a requirement; name REQ ids in the Task or Test column"
    ]


def test_vague_unmeasurable_requirements(tmp_path: Path) -> None:
    spec = SPEC + "- REQ-010-03: The limiter must be fast and secure.\n"
    tasks = TASKS + "| T-010-03 | speed (REQ-010-03) | bench | low | [ ] |\n"
    found = _messages(_spec(tmp_path, spec=spec, tasks=tasks), MEDIUM)
    assert found == ["REQ-010-03: 'fast' with nothing measurable"]


def test_task_paths_missing_from_the_plan(tmp_path: Path) -> None:
    tasks = TASKS + "| T-010-03 | `src/extra.py` helper (REQ-010-01) | x | low | [ ] |\n"
    assert _messages(_spec(tmp_path, tasks=tasks), MEDIUM) == ["`src/extra.py` is not in plan.md"]


def test_missing_files_requirements_and_duplicates(tmp_path: Path) -> None:
    spec_dir = tmp_path / "specs" / "011-x"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text("# Spec 011\n")
    levels = {(f.level, f.where) for f in analyze(spec_dir)}
    assert (CRITICAL, "plan.md") in levels and (HIGH, "spec.md") in levels
    dup = SPEC + "- REQ-010-03: Allow 10 requests per second per key.\n"
    tasks = TASKS + "| T-010-03 | dup (REQ-010-03) | x | low | [ ] |\n"
    assert _messages(_spec(tmp_path, spec=dup, tasks=tasks), LOW) == [
        "REQ-010-03 repeats REQ-010-01"
    ]


def test_approve_refuses_a_spec_with_critical_findings(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    spec = repo / "specs" / "009-demo" / "spec.md"
    spec.write_text(spec.read_text() + "- [NEEDS CLARIFICATION: which window?]\n")
    assert main(["analyze", "009"]) == 1
    assert main(["approve", "009"]) == 2
    assert "resolve the CRITICAL findings" in capsys.readouterr().err
    assert main(["approve", "009", "--anyway"]) == 0


def test_constitution_rules_reach_the_brief(repo: Path, cfg: config.Config) -> None:
    (repo / "specs" / "constitution.md").write_text(
        "# Rules\n- Code MUST NOT log secrets.\n- Prefer small modules.\n- NEVER skip tests.\n"
    )
    brief = build_brief(cfg, repo / "specs" / "009-demo", ["T-009-02"])
    assert "## Project rules" in brief
    assert "- Code MUST NOT log secrets." in brief and "NEVER skip tests" in brief
    assert "Prefer small modules" not in brief  # guidance, not a rule


def test_init_writes_a_constitution_once(tmp_path: Path) -> None:
    lines = init_project(tmp_path, "generic")
    constitution = tmp_path / "specs" / "constitution.md"
    assert constitution.exists() and any("constitution.md" in line for line in lines)
    constitution.write_text("mine\n")
    init_project(tmp_path, "generic")
    assert constitution.read_text() == "mine\n"


def test_template_guidance_is_ignored_even_across_lines() -> None:
    from specsteward.analyze import without_comments

    text = "a\n<!-- guidance\n[NEEDS CLARIFICATION: inside a comment]\n-->\nb <!-- x --!> c\n"
    stripped = without_comments(text)
    assert "NEEDS CLARIFICATION" not in stripped and stripped.count("\n") == text.count("\n")
    assert "b  c" in stripped
    assert without_comments("x <!-- never closed\n[NEEDS CLARIFICATION: y]") == "x \n"
