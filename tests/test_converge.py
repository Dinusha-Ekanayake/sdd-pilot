"""Converge: after every task is ticked, appended tasks go through approval and resume the run."""

from pathlib import Path

import pytest

from specsteward import config
from specsteward import state as run_state
from specsteward.__main__ import main
from specsteward.tasks import parse_tasks

from .conftest import tasks_file, tick, write_config

APPENDED = (
    "\n## Convergence 2026-11-04\n\n"
    "| ID | Task | Test | Risk | Status |\n|---|---|---|---|---|\n"
    "| T-009-07 | handle empty frames (REQ-009-01; partial) | empty input | high | [ ] |\n"
)


def _finish_all(cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)
    for task in parse_tasks(tasks_file(cfg.root)):
        if task.pending:
            tick(cfg, task.id)


def test_converge_waits_until_every_task_is_ticked(cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)
    with pytest.raises(ValueError, match="after every task is ticked"):
        run_state.converge_round(cfg)


def test_converge_gives_the_next_free_task_id(cfg: config.Config) -> None:
    _finish_all(cfg)
    assert run_state.converge_round(cfg) == {
        "status": "converge",
        "round": 1,
        "next_id": "T-009-07",
    }


def test_appended_tasks_need_approval_then_the_run_resumes(cfg: config.Config) -> None:
    _finish_all(cfg)
    run_state.converge_round(cfg)
    path = tasks_file(cfg.root)
    path.write_text(path.read_text() + APPENDED)  # what the converger does
    step = run_state.next_step(cfg)
    assert step["status"] == "halted" and "approve it again" in step["reason"]
    run_state.approve(cfg, "009", via="terminal")  # the user approves the new task
    run_state.resume(cfg.root)
    step = run_state.next_step(cfg)
    assert step["status"] == "run" and step["tasks"] == ["T-009-07"]


def test_approve_refuses_changed_existing_rows_mid_run(cfg: config.Config) -> None:
    _finish_all(cfg)
    path = tasks_file(cfg.root)
    text = path.read_text().replace("| low | [x] |", "| low | [ ] |", 1) + APPENDED
    path.write_text(text)
    with pytest.raises(ValueError, match="existing tasks changed during the run"):
        run_state.approve(cfg, "009", via="terminal")


def test_approve_refuses_appended_rows_that_are_already_ticked(cfg: config.Config) -> None:
    _finish_all(cfg)
    path = tasks_file(cfg.root)
    path.write_text(path.read_text() + APPENDED.replace("| high | [ ] |", "| high | [x] |"))
    with pytest.raises(ValueError, match="must be open"):
        run_state.approve(cfg, "009", via="terminal")


def test_converge_round_cap_halts(repo: Path) -> None:
    cfg = write_config(repo, "[limits]\nmax_converge_rounds = 1\n")
    _finish_all(cfg)
    assert run_state.converge_round(cfg)["status"] == "converge"
    result = run_state.converge_round(cfg)
    assert result["status"] == "halted" and "converge round cap" in result["reason"]


def test_cli_converge_and_approve_start_resumes(
    repo: Path, cfg: config.Config, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    _finish_all(cfg)
    assert main(["converge"]) == 0
    assert '"next_id": "T-009-07"' in capsys.readouterr().out
    path = tasks_file(repo)
    path.write_text(path.read_text() + APPENDED)
    assert run_state.next_step(cfg)["status"] == "halted"
    assert main(["approve", "009", "--start", "--no-branch-check"]) == 0  # resumes, no restart
    state = run_state.require(repo)
    assert state["halted"] is None and state["converge_rounds"] == 1
    assert main(["agent", "converger"]) == 0
