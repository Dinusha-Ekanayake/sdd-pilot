"""Edge cases across sessions: subagents in flight, run ownership, separate projects."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from specsteward import config, trust
from specsteward import state as run_state
from specsteward.__main__ import main
from specsteward.hooks import session_context, stop_decision

from .conftest import BASE_CONFIG, PLAN, SPEC, TASKS, tick

ROOT = Path(__file__).resolve().parent.parent
OWNER, OTHER = "session-owner", "session-other"


def _start(cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)


def _bind(
    cfg: config.Config, session_id: str, command: str = "bash .sdd/bin/sdd start 009"
) -> None:
    payload = {"session_id": session_id, "tool_input": {"command": command}}
    run_state.bind_owner(cfg, payload)


# --- subagents in flight -------------------------------------------------------------


def test_waiting_for_a_subagent_is_not_a_stop_without_progress(cfg: config.Config) -> None:
    _start(cfg)
    assert stop_decision(cfg) is not None  # first stop: continue
    run_state.record_agent(cfg, "implementer", fresh=True)  # launched, still working
    assert stop_decision(cfg) is None  # the session may wait for it
    assert stop_decision(cfg) is None  # however often it stops
    assert run_state.require(cfg.root)["halted"] is None


def test_a_finished_subagent_counts_as_progress(cfg: config.Config) -> None:
    _start(cfg)
    assert stop_decision(cfg) is not None
    run_state.record_agent(cfg, "implementer", fresh=True)
    run_state.observe_agent(cfg, "specsteward:implementer")  # it finished
    assert stop_decision(cfg) is not None  # its report needs handling: continue
    assert stop_decision(cfg) is None  # nothing since then: halt
    assert "no task completed" in run_state.load(cfg.root)["halted"]  # type: ignore[index]


def test_in_flight_expires_so_the_protection_cannot_be_lost(cfg: config.Config) -> None:
    _start(cfg)
    run_state.record_agent(cfg, "implementer", fresh=True)
    state = run_state.require(cfg.root)
    state["last_agent_at"] = time.time() - run_state.IN_FLIGHT_SECONDS - 1
    run_state.save(cfg.root, state)
    assert stop_decision(cfg) is not None  # treated as an ordinary stop again


def test_subagents_of_other_tools_are_not_counted(cfg: config.Config) -> None:
    _start(cfg)
    run_state.observe_agent(cfg, "Explore")
    run_state.observe_agent(cfg, "code-reviewer")
    assert run_state.require(cfg.root)["observed_agent_runs"] == 0
    run_state.observe_agent(cfg, "specsteward:reviewer")
    run_state.observe_agent(cfg, None)  # older Claude Code: no type, counted
    assert run_state.require(cfg.root)["observed_agent_runs"] == 2


# --- one run, one owning session ------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "bash .sdd/bin/sdd start 009",
        "bash .sdd/bin/sdd approve 009 --via terminal --start",
        "bash .sdd/bin/sdd resume",
        "bash .sdd/bin/sdd claim",
    ],
)
def test_the_session_that_starts_resumes_or_claims_owns_the_run(
    cfg: config.Config, command: str
) -> None:
    _start(cfg)
    _bind(cfg, OWNER, command)
    assert run_state.require(cfg.root)["owner_session"] == OWNER


@pytest.mark.parametrize(
    "command", ["bash .sdd/bin/sdd status", "bash .sdd/bin/sdd approve 009", "git status"]
)
def test_other_commands_do_not_take_ownership(cfg: config.Config, command: str) -> None:
    _start(cfg)
    _bind(cfg, OWNER, command)
    assert "owner_session" not in run_state.require(cfg.root)


def test_another_session_is_never_told_to_continue_the_run(cfg: config.Config) -> None:
    _start(cfg)
    _bind(cfg, OWNER)
    for _ in range(3):
        assert stop_decision(cfg, OTHER) is None
    assert run_state.require(cfg.root)["halted"] is None  # and never halts it either
    assert stop_decision(cfg, OWNER) is not None


def test_another_sessions_agents_and_tokens_do_not_count(
    cfg: config.Config, tmp_path: Path
) -> None:
    _start(cfg)
    _bind(cfg, OWNER)
    run_state.observe_agent(cfg, "specsteward:implementer", OTHER)
    assert run_state.require(cfg.root)["observed_agent_runs"] == 0
    transcript = tmp_path / "other.jsonl"
    transcript.write_text("")
    assert run_state.observe_usage(cfg, str(transcript), OTHER) is None


def test_another_session_is_told_whose_run_it_is(cfg: config.Config) -> None:
    _start(cfg)
    _bind(cfg, OWNER)
    assert "belongs to another Claude Code session" in session_context(cfg, OTHER)
    assert "sdd claim" in session_context(cfg, OTHER)
    assert "another" not in session_context(cfg, OWNER)


def test_cli_claim_needs_an_active_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert main(["claim"]) == 2
    assert "no active specsteward run" in capsys.readouterr().err
    assert main(["start", "009", "--no-branch-check"]) == 0
    assert main(["claim"]) == 0


def test_bind_hook_reads_the_payload_passed_by_the_launcher(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert main(["start", "009", "--no-branch-check"]) == 0
    payload = {"session_id": OWNER, "tool_input": {"command": "bash .sdd/bin/sdd claim"}}
    monkeypatch.setenv("SDD_HOOK_PAYLOAD", json.dumps(payload))
    assert main(["hook-bind"]) == 0
    assert run_state.require(repo)["owner_session"] == OWNER


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_launcher_skips_python_for_unrelated_bash_calls(repo: Path) -> None:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "SDD_PYTHON": "no-such-python"}
    payload = json.dumps({"session_id": OWNER, "tool_input": {"command": "ls -la"}})
    proc = subprocess.run(
        [str(shutil.which("bash")), str(ROOT / "bin" / "sdd"), "hook-bind"],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0 and proc.stderr == ""  # Python was never needed


# --- separate projects never mix ----------------------------------------------------------


def _project(base: Path, name: str) -> config.Config:
    root = base / name
    spec = root / "specs" / "009-demo"
    spec.mkdir(parents=True)
    for file, text in (("tasks.md", TASKS), ("spec.md", SPEC), ("plan.md", PLAN)):
        (spec / file).write_text(text, encoding="utf-8")
    (root / "sdd.toml").write_text(BASE_CONFIG, encoding="utf-8")
    trust.trust_config(root)
    cfg = config.load(root)
    run_state.approve(cfg, "009", via="terminal")
    return cfg


def test_two_projects_keep_separate_runs_trust_and_approvals(tmp_path: Path) -> None:
    shop, blog = _project(tmp_path, "shop"), _project(tmp_path, "blog")
    _start(shop)
    _start(blog)
    tick(shop, "T-009-02")
    assert run_state.summary(shop.root).startswith("Spec 009: 2 done")
    assert run_state.summary(blog.root).startswith("Spec 009: 1 done")  # untouched
    (blog.root / "sdd.toml").write_text(BASE_CONFIG + "# edited\n", encoding="utf-8")
    assert trust.config_trusted(shop.root) and not trust.config_trusted(blog.root)
    run_state.stop(shop.root)
    assert run_state.require(blog.root)["active"] is True


def test_same_spec_number_in_two_projects_is_approved_separately(tmp_path: Path) -> None:
    shop, blog = _project(tmp_path, "shop"), _project(tmp_path, "blog")
    spec = blog.root / "specs" / "009-demo" / "spec.md"
    spec.write_text(spec.read_text() + "- REQ-009-02: only in blog.\n")
    assert run_state.approval_problem(shop, "009", shop.spec_dir("009")) is None
    assert run_state.approval_problem(blog, "009", blog.spec_dir("009")) is not None


# --- several sessions running the same bot ------------------------------------------------

WINDOWS_LINES = [
    r'bun run --cwd "C:/Users/me/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7" '
    "--shell=bun --silent start",
    r'"C:\Users\me\.local\bin\bun.exe" server.ts',
    r'bun run --cwd "C:/Users/me/.claude/plugins/cache/claude-plugins-official/telegram/0.0.7" '
    "--shell=bun --silent start",
]
POSIX_LINES = [
    "bun run --cwd /home/me/.claude/plugins/cache/claude-plugins-official/discord/0.1.0 start",
    "/usr/bin/python3 something-else.py telegram",
]


def test_running_servers_are_counted_per_channel() -> None:
    from specsteward.remote import running_servers

    assert running_servers(WINDOWS_LINES) == {"telegram": 2}
    assert running_servers(POSIX_LINES) == {"discord": 1}
    assert running_servers([]) == {}


def test_doctor_warns_when_several_sessions_run_the_bot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from specsteward import doctor
    from specsteward.init import init_project

    monkeypatch.setenv("TELEGRAM_STATE_DIR", str(tmp_path / "tg"))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    monkeypatch.setattr(doctor, "running_servers", lambda: {"telegram": 3})
    (tmp_path / "proj").mkdir()
    init_project(tmp_path / "proj", "generic")
    whats = [f.what for f in doctor.run_doctor(tmp_path / "proj")]
    assert any(w.startswith("3 telegram servers are running") for w in whats)


# --- the implementer's own checks do not count --------------------------------------------


def test_implementer_checks_while_working_never_halt_the_run(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from .conftest import write_config

    failing = f'[[check]]\nname = "t"\ncmd = [{json.dumps(sys.executable)}, "-c", "exit(1)"]\n'
    write_config(repo, failing)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert main(["start", "009", "--no-branch-check"]) == 0
    assert main(["next"]) == 0
    for _ in range(3):  # RED, RED again: how test-first work looks
        assert main(["check"]) == 1
    assert run_state.require(repo)["halted"] is None
    assert main(["check", "--task", "T-009-02"]) == 1  # the orchestrator's gate counts
    assert main(["check", "--task", "T-009-02"]) == 1
    assert "same check failure twice" in run_state.require(repo)["halted"]


# --- the user's sign-off on human tasks --------------------------------------------------


def test_signoff_turns_a_waiting_human_task_into_done(cfg: config.Config) -> None:
    from specsteward.tasks import parse_tasks

    from .conftest import tasks_file

    _start(cfg)
    tick(cfg, "T-009-06")  # human risk: prepared, waiting at [?]
    run_state.signoff(cfg, "T-009-06")
    statuses = {t.id: t.status for t in parse_tasks(tasks_file(cfg.root))}
    assert statuses["T-009-06"] == "[x]"
    assert run_state.integrity_problem(cfg, run_state.require(cfg.root)) is None  # no alarm


def test_signoff_only_for_tasks_waiting_at_question_mark(cfg: config.Config) -> None:
    _start(cfg)
    with pytest.raises(ValueError, match="not waiting for sign-off"):
        run_state.signoff(cfg, "T-009-02")  # still open
    with pytest.raises(ValueError, match="not waiting for sign-off"):
        run_state.signoff(cfg, "T-009-99")


def test_signoff_is_a_gate() -> None:
    from specsteward.init import ASK

    assert "Bash(bash .sdd/bin/sdd signoff:*)" in ASK


# --- a Python path with a space (C:\Users\First Last\...) ---------------------------------


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_launcher_runs_a_python_whose_path_has_a_space(repo: Path, tmp_path: Path) -> None:
    folder = tmp_path / "First Last" / "python"
    folder.mkdir(parents=True)
    wrapper = folder / "python"  # stands in for C:\Users\First Last\...\python.exe
    real = Path(sys.executable).as_posix()
    wrapper.write_text(f'#!/usr/bin/env bash\nexec "{real}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo), "SDD_PYTHON": wrapper.as_posix()}
    proc = subprocess.run(
        [str(shutil.which("bash")), str(ROOT / "bin" / "sdd"), "--version"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("specsteward ")


def test_signoff_still_works_after_the_run_was_stopped(cfg: config.Config) -> None:
    from specsteward.tasks import parse_tasks

    from .conftest import tasks_file

    _start(cfg)
    tick(cfg, "T-009-06")
    run_state.stop(cfg.root)  # shipped and stopped with the human task still at [?]
    run_state.signoff(cfg, "T-009-06")
    assert {t.id: t.status for t in parse_tasks(tasks_file(cfg.root))}["T-009-06"] == "[x]"


def test_signoff_without_any_run_says_so(repo: Path, cfg: config.Config) -> None:
    with pytest.raises(ValueError, match="no specsteward run in this project"):
        run_state.signoff(cfg, "T-009-06")
