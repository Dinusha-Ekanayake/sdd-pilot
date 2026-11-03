"""Regressions for the security review: an agent editing project files to skip gates."""

from pathlib import Path

import pytest

from sdd_pilot import config
from sdd_pilot import state as run_state
from sdd_pilot.hooks import stop_decision

from .conftest import tasks_file, tick, write_config


def _start(cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)


def test_hand_ticked_task_halts_the_run(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    path = tasks_file(repo)
    path.write_text(path.read_text().replace("| human | [ ] |", "| human | [x] |"))
    step = run_state.next_step(cfg)
    assert step["status"] == "halted" and "T-009-06" in step["reason"]


def test_deleted_task_row_halts_the_run(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    path = tasks_file(repo)
    path.write_text(
        "\n".join(row for row in path.read_text().splitlines() if "T-009-04" not in row)
    )
    assert run_state.next_step(cfg)["status"] == "halted"


def test_lowering_a_risk_voids_the_approval(repo: Path) -> None:
    cfg = write_config(repo, '[review]\nskip = ["low"]\n')
    _start(cfg)
    path = tasks_file(repo)
    path.write_text(path.read_text().replace("| values | high |", "| values | low |"))
    step = run_state.next_step(cfg)
    assert step["status"] == "halted" and "approve it again" in step["reason"]


def test_editing_the_plan_voids_the_approval(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    plan = repo / "specs" / "009-demo" / "plan.md"
    plan.write_text(plan.read_text() + "| `src/backdoor.py` | added after approval |\n")
    assert run_state.next_step(cfg)["status"] == "halted"


def test_done_refuses_on_a_tampered_table(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    run_state.next_step(cfg)
    path = tasks_file(repo)
    path.write_text(path.read_text().replace("| low | [ ] |", "| low | [x] |"))
    with pytest.raises(ValueError, match="outside `sdd done`"):
        run_state.complete(cfg, "T-009-02")


def test_stop_hook_never_continues_on_a_tampered_table(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    path = tasks_file(repo)
    path.write_text(path.read_text().replace("[ ]", "[x]"))  # "everything is done"
    assert stop_decision(cfg) is None
    assert "outside `sdd done`" in run_state.load(repo)["halted"]  # type: ignore[index]


def test_ticks_through_done_are_accepted(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    tick(cfg, "T-009-02")
    assert run_state.next_step(cfg)["status"] == "run"


def test_tree_changing_while_the_gate_runs_is_not_a_pass(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    first, _ = run_state.next_step(cfg)["tasks"]
    before = run_state.run_tree(cfg)
    (repo / "swapped_in_after_the_tests.py").write_text("x = 1\n")
    with pytest.raises(ValueError, match="changed while the gate ran"):
        run_state.record_pass(cfg, before)
    run_state.record_pass(cfg, run_state.run_tree(cfg))
    run_state.record_review(cfg, first, "clean")
    run_state.complete(cfg, first)
