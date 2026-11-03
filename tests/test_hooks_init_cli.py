import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sdd_pilot import config, trust
from sdd_pilot import state as run_state
from sdd_pilot.__main__ import main
from sdd_pilot.hooks import format_file, stop_decision, write_shim
from sdd_pilot.init import ASK, init_project, render_config
from sdd_pilot.remote import telegram_status
from sdd_pilot.tasks import parse_tasks

from .conftest import tasks_file, write_config

ROOT = Path(__file__).resolve().parent.parent

# --- stop hook --------------------------------------------------------------------


def test_stop_hook_inactive_without_run(cfg: config.Config) -> None:
    assert stop_decision(cfg) is None


def test_stop_hook_blocks_then_halts_without_progress(cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)
    first = stop_decision(cfg)
    assert first is not None and first["decision"] == "block"
    assert "bash .sdd/bin/sdd next" in first["reason"]
    assert stop_decision(cfg) is None
    assert "no task completed" in run_state.load(cfg.root)["halted"]  # type: ignore[index]


def test_stop_hook_keeps_blocking_while_progress_is_made(cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)
    assert stop_decision(cfg) is not None
    run_state.complete(cfg.root, "T-009-02", human=False)
    assert stop_decision(cfg) is not None


def test_stop_hook_allows_stop_when_all_done(repo: Path, cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)
    for task in parse_tasks(tasks_file(repo)):
        if task.pending:
            run_state.complete(repo, task.id, human=False)
    assert stop_decision(cfg) is None


# --- format hook ------------------------------------------------------------------


def _formatter_cfg(repo: Path) -> config.Config:
    script = "import sys,pathlib; p=pathlib.Path(sys.argv[1]); p.write_text(p.read_text().upper())"
    return config.from_dict(repo, {"format": {".py": [[sys.executable, "-c", script, "{file}"]]}})


def test_format_hook_runs_configured_formatter(repo: Path) -> None:
    target = repo / "mod.py"
    target.write_text("x = 1\n")
    format_file(_formatter_cfg(repo), {"tool_input": {"file_path": str(target)}})
    assert target.read_text() == "X = 1\n"


def test_format_hook_does_nothing_for_an_untrusted_config(repo: Path) -> None:
    target = repo / "mod.py"
    target.write_text("x = 1\n")
    (repo / "sdd.toml").write_text("# changed by a clone or an agent\n")
    format_file(_formatter_cfg(repo), {"tool_input": {"file_path": str(target)}})
    assert target.read_text() == "x = 1\n"


def test_format_hook_ignores_other_suffixes_and_missing_files(repo: Path) -> None:
    notes = repo / "notes.md"
    notes.write_text("x = 1\n")
    cfg = _formatter_cfg(repo)
    format_file(cfg, {"tool_input": {"file_path": str(notes)}})
    format_file(cfg, {"tool_input": {"file_path": str(repo / "gone.py")}})
    format_file(cfg, {})
    assert notes.read_text() == "x = 1\n"


# --- init -------------------------------------------------------------------------


def test_init_creates_everything_once(tmp_path: Path) -> None:
    first = init_project(tmp_path, "python")
    assert "wrote sdd.toml (python preset, trusted)" in first
    assert trust.config_trusted(tmp_path)
    assert (tmp_path / "specs" / "_template" / "tasks.md").exists()
    assert ".sdd/" in (tmp_path / ".gitignore").read_text()
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text())
    assert set(ASK) <= set(settings["permissions"]["ask"])
    second = init_project(tmp_path, "python")
    assert second == ["kept existing sdd.toml"]  # still trusted, so no hint
    config.load(tmp_path)  # the written preset is valid


def test_init_does_not_trust_an_existing_config(tmp_path: Path) -> None:
    (tmp_path / "sdd.toml").write_text("[project]\n")
    lines = init_project(tmp_path, "python")
    assert "kept existing sdd.toml" in lines and not trust.config_trusted(tmp_path)
    assert any("sdd trust" in line for line in lines)


def test_cli_trust_records_the_config(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    (repo / "sdd.toml").write_text("[brief]\ngraphify = false\n# edited\n")
    assert not trust.config_trusted(repo)
    assert main(["trust"]) == 0
    assert "trusted sdd.toml" in capsys.readouterr().out
    assert trust.config_trusted(repo)


def test_init_keeps_existing_settings(tmp_path: Path) -> None:
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}, "model": "x"}))
    init_project(tmp_path, "generic")
    merged = json.loads(settings.read_text())
    assert merged["model"] == "x" and "Bash(ls:*)" in merged["permissions"]["allow"]


@pytest.mark.parametrize("preset", ["python", "node", "generic"])
def test_every_preset_is_valid_toml(tmp_path: Path, preset: str) -> None:
    (tmp_path / "sdd.toml").write_text(render_config(tmp_path, preset), encoding="utf-8")
    config.load(tmp_path)


def test_python_preset_uses_project_venv(tmp_path: Path) -> None:
    (tmp_path / ".venv" / "bin").mkdir(parents=True)
    (tmp_path / ".venv" / "bin" / "python").write_text("")
    assert '".venv/bin/python", "-m", "pytest"' in render_config(tmp_path, "python")


def test_unknown_preset_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="preset"):
        render_config(tmp_path, "cobol")


# --- remote -------------------------------------------------------------------------


def test_remote_not_paired(tmp_path: Path) -> None:
    status = telegram_status(tmp_path)
    assert status["ready"] is False and "not paired" in status["problems"][0]


def test_remote_ready_with_single_allowlisted_user(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("TELEGRAM_BOT_TOKEN=x\n")
    (tmp_path / "access.json").write_text(
        json.dumps({"dmPolicy": "allowlist", "allowFrom": ["42"]})
    )
    assert telegram_status(tmp_path) == {
        "channel": "telegram",
        "ready": True,
        "chat_ids": ["42"],
        "problems": [],
        "token_set": True,
    }


def test_remote_flags_unsafe_setups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    access = {"dmPolicy": "pairing", "allowFrom": ["1", "2"], "groups": {"-100": {}}}
    (tmp_path / "access.json").write_text(json.dumps(access))
    problems = " | ".join(telegram_status(tmp_path)["problems"])
    for expected in ("no bot token", "more than one user", "not 'allowlist'", "in groups"):
        assert expected in problems


# --- CLI ----------------------------------------------------------------------------


def test_cli_round_trip(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert main(["start", "009"]) == 2  # tmp_path is not a git repo
    assert main(["start", "009", "--no-branch-check"]) == 0
    assert main(["next"]) == 0
    step = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert step["tasks"] == ["T-009-02", "T-009-03"]
    assert main(["brief", "T-009-02"]) == 0
    assert (repo / ".sdd" / "briefs" / "T-009-02.md").exists()
    for argv in (["agent", "implementer", "--fresh"], ["assume", "T-009-02", "x"]):
        assert main(argv) == 0
    assert main(["review", "T-009-02", "clean"]) == 0
    assert main(["done", "T-009-02"]) == 0
    assert main(["check"]) == 0
    assert main(["status"]) == 0
    assert "1 done" not in capsys.readouterr().out.split("Spec 009:")[0]
    assert main(["halt", "need user"]) == 0
    capsys.readouterr()
    assert main(["hook-stop"]) == 0
    assert capsys.readouterr().out == ""  # halted runs never block a stop
    assert main(["resume"]) == 0
    assert main(["status", "--json"]) == 0
    assert main(["stop"]) == 0
    assert main(["remote"]) == 0


def test_cli_check_records_failures(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_config(
        repo, f'[[check]]\nname = "t"\ncmd = [{json.dumps(sys.executable)}, "-c", "exit(1)"]\n'
    )
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert main(["start", "009", "--no-branch-check"]) == 0
    assert main(["check", "--task", "T-009-02"]) == 1
    assert main(["check", "--task", "T-009-02"]) == 1
    assert "same check failure" in run_state.load(repo)["halted"]  # type: ignore[index]


def test_cli_approve(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert main(["approve", "009", "--via", "telegram"]) == 0
    assert (repo / ".sdd" / "approvals.log").exists()


def test_hooks_are_silent_outside_sdd_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    for hook in ("hook-stop", "hook-session-start"):
        assert main([hook]) == 0
    assert capsys.readouterr().out == ""
    assert not (tmp_path / ".sdd").exists()


def test_session_start_writes_shim_and_context(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    assert main(["hook-session-start"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "bash .sdd/bin/sdd" in payload["hookSpecificOutput"]["additionalContext"]
    assert (repo / ".sdd" / "bin" / "sdd").read_text().startswith("#!/usr/bin/env bash")


def test_cli_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert main(["init", "--preset", "generic"]) == 0
    assert (tmp_path / "sdd.toml").exists() and (tmp_path / ".sdd" / "bin" / "sdd").exists()


def test_cli_errors_return_2(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert main(["status"]) == 2  # no sdd.toml


# --- launcher (end to end through bash) --------------------------------------------------


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_launcher_and_shim_run_the_cli(repo: Path) -> None:
    # Resolve through PATH: on Windows a bare "bash" can hit WSL in System32 instead.
    bash = shutil.which("bash")
    assert bash is not None
    shim = write_shim(repo, ROOT / "bin" / "sdd")
    proc = subprocess.run(
        [bash, shim.relative_to(repo).as_posix(), "status"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={**os.environ, "SDD_PYTHON": sys.executable},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "No SDD run in this project."
