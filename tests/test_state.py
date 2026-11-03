import json
from pathlib import Path

import pytest

from sdd_pilot import config, trust
from sdd_pilot import state as run_state
from sdd_pilot.tasks import HUMAN, parse_tasks

from .conftest import SPEC, tasks_file


def _start(cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)


def test_start_refuses_unapproved_spec(repo: Path, cfg: config.Config) -> None:
    (repo / "specs" / "009-demo" / "spec.md").write_text(SPEC.replace("Approved", "Draft"))
    with pytest.raises(ValueError, match="not approved"):
        _start(cfg)


def test_start_checks_branch_outside_git(cfg: config.Config) -> None:
    with pytest.raises(ValueError, match="git"):
        run_state.start(cfg, "009")


def test_branch_check_can_be_disabled_in_config(repo: Path) -> None:
    (repo / "sdd.toml").write_text('[project]\nbranch_prefix = ""\n')
    assert run_state.start(config.load(repo), "009")["active"] is True


def test_next_step_reports_group_and_reviewer(cfg: config.Config) -> None:
    _start(cfg)
    step = run_state.next_step(cfg)
    assert step["tasks"] == ["T-009-02", "T-009-03"]
    assert step["reviewer_model"] == "opus"
    assert step["restart_implementer"] is False


def test_same_failure_twice_halts(cfg: config.Config) -> None:
    _start(cfg)
    assert run_state.record_failure(cfg, "T-009-02", "abc")["halted"] is None
    assert "same check failure twice" in run_state.record_failure(cfg, "T-009-02", "abc")["halted"]
    assert run_state.next_step(cfg)["status"] == "halted"


def test_fix_attempt_cap_halts(cfg: config.Config) -> None:
    _start(cfg)
    for sig in ("a", "b", "c"):
        assert run_state.record_failure(cfg, "T-009-02", sig)["halted"] is None
    assert "fix attempt cap" in run_state.record_failure(cfg, "T-009-02", "d")["halted"]


def test_review_round_cap_halts_only_with_open_findings(cfg: config.Config) -> None:
    _start(cfg)
    assert run_state.record_review(cfg, "T-009-02", "changes")["halted"] is None
    assert "review round cap" in run_state.record_review(cfg, "T-009-02", "changes")["halted"]
    run_state.resume(cfg.root)
    assert run_state.record_review(cfg, "T-009-02", "clean")["halted"] is None
    with pytest.raises(ValueError, match="verdict"):
        run_state.record_review(cfg, "T-009-02", "maybe")


def test_agent_run_cap_and_restart_flag(repo: Path) -> None:
    (repo / "sdd.toml").write_text("[limits]\nmax_agent_runs = 1\nrestart_after_tasks = 1\n")
    cfg = config.load(repo)
    _start(cfg)
    run_state.complete(repo, "T-009-02", human=False)
    assert run_state.next_step(cfg)["restart_implementer"] is True
    assert run_state.record_agent(cfg, "implementer", fresh=True)["halted"] is None
    assert run_state.next_step(cfg)["restart_implementer"] is False
    assert "agent run cap" in run_state.record_agent(cfg, "reviewer", fresh=False)["halted"]


def test_resume_clears_halt_and_counters(cfg: config.Config) -> None:
    _start(cfg)
    run_state.record_failure(cfg, "T-009-02", "abc")
    run_state.record_failure(cfg, "T-009-02", "abc")
    state = run_state.resume(cfg.root)
    assert state["halted"] is None
    assert state["tasks"]["T-009-02"]["failures"] == []


def test_done_when_all_tasks_closed(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    for task in parse_tasks(tasks_file(repo)):
        if task.pending:
            run_state.complete(repo, task.id, human=task.risk == "human")
    assert run_state.next_step(cfg) == {"status": "done", "spec": "009"}
    assert parse_tasks(tasks_file(repo))[-1].status == HUMAN


def test_stop_and_require(cfg: config.Config) -> None:
    _start(cfg)
    run_state.stop(cfg.root)
    with pytest.raises(ValueError, match="no active"):
        run_state.next_step(cfg)


def test_approve_updates_status_and_logs(repo: Path, cfg: config.Config) -> None:
    spec = repo / "specs" / "009-demo" / "spec.md"
    spec.write_text(SPEC.replace("Approved (2026-11-02)", "Draft"))
    stamp = run_state.approve(cfg, "009", via="telegram")
    assert stamp.startswith("Approved (")
    assert cfg.is_approved(spec.read_text())
    assert "REQ-009-01" in spec.read_text()  # nothing else touched
    entry = json.loads((repo / ".sdd" / "approvals.log").read_text().splitlines()[-1])
    assert entry["spec"] == "009" and entry["via"] == "telegram"


def test_hand_edited_status_line_is_not_an_approval(repo: Path, cfg: config.Config) -> None:
    spec = repo / "specs" / "009-demo" / "spec.md"
    spec.write_text(SPEC.replace("Approved (2026-11-02)", "Draft"))
    run_state.approve(cfg, "009", via="terminal")
    trust.record_approval(repo, "009", "forged-or-stale")  # e.g. a different spec version
    spec.write_text(SPEC)  # an agent writes "Approved" itself
    with pytest.raises(ValueError, match="changed after it was approved"):
        _start(cfg)


def test_status_line_without_any_recorded_approval(repo: Path, cfg: config.Config) -> None:
    store = trust.store_path()
    store.write_text(store.read_text().replace('"009"', '"008"'))
    with pytest.raises(ValueError, match="no recorded approval"):
        _start(cfg)


def test_approval_follows_spec_edits(repo: Path, cfg: config.Config) -> None:
    spec = repo / "specs" / "009-demo" / "spec.md"
    run_state.approve(cfg, "009", via="terminal")
    entry = json.loads((repo / ".sdd" / "approvals.log").read_text().splitlines()[-1])
    assert entry["sha256"] == trust.file_hash(spec)
    _start(cfg)
    spec.write_text(spec.read_text() + "- REQ-009-02: slipped in after approval.\n")
    step = run_state.next_step(cfg)
    assert step["status"] == "halted" and "changed after it was approved" in step["reason"]
    run_state.approve(cfg, "009", via="terminal")  # the user re-approves
    run_state.resume(repo)
    assert run_state.next_step(cfg)["status"] == "run"


@pytest.mark.parametrize("spec", ["*", "../009", "9", "0091"])
def test_spec_number_is_validated(cfg: config.Config, spec: str) -> None:
    with pytest.raises(ValueError, match="three-digit"):
        cfg.spec_dir(spec)


def test_approve_requires_status_line(repo: Path, cfg: config.Config) -> None:
    (repo / "specs" / "009-demo" / "spec.md").write_text("# no status\n")
    with pytest.raises(ValueError, match="no status line"):
        run_state.approve(cfg, "009", via="terminal")


def test_summary_for_phone(repo: Path, cfg: config.Config) -> None:
    assert run_state.summary(repo) == "No SDD run in this project."
    _start(cfg)
    run_state.record_assumption(repo, "T-009-02", "right-closed windows")
    run_state.complete(repo, "T-009-06", human=True)
    run_state.halt(repo, run_state.require(repo), "need a decision")
    text = run_state.summary(repo)
    assert "Spec 009: 1 done, 1 waiting for you, 4 open. Running." in text
    assert "Halted: need a decision" in text
    assert "Sign-off needed: T-009-06" in text
    assert "T-009-02: right-closed windows" in text
