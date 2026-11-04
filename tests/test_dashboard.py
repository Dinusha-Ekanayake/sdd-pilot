import io
import json
from pathlib import Path

import pytest

from sdd_pilot import config
from sdd_pilot import state as run_state
from sdd_pilot.__main__ import main
from sdd_pilot.dashboard import DASHBOARD_FILE, render_dashboard, status_line
from sdd_pilot.init import enable_statusline
from sdd_pilot.tasks import parse_tasks

from .conftest import tasks_file, tick


def _start(cfg: config.Config) -> None:
    run_state.start(cfg, "009", check_branch=False)


def test_status_line_is_empty_without_a_run() -> None:
    assert status_line(None, []) == ""


def test_status_line_shows_progress_next_task_and_halts(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    tasks = parse_tasks(tasks_file(repo))
    assert status_line(run_state.require(repo), tasks) == "SDD 009 ▸ 1/6 ✓ · next T-009-02"
    tick(cfg, "T-009-06")
    run_state.halt(repo, run_state.require(repo), "x" * 80)
    line = status_line(run_state.require(repo), parse_tasks(tasks_file(repo)))
    assert "1 awaiting you" in line and line.endswith("…") and "halted: " in line


def test_dashboard_is_regenerated_on_every_state_change(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    page = (repo / DASHBOARD_FILE).read_text(encoding="utf-8")
    assert "Spec 009" in page and "T-009-02" in page and "running" in page
    run_state.halt(repo, run_state.require(repo), "need a decision")
    assert "need a decision" in (repo / DASHBOARD_FILE).read_text(encoding="utf-8")


def test_dashboard_escapes_repository_text(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    run_state.record_assumption(repo, "T-009-02", "<script>alert(1)</script>")
    page = render_dashboard(run_state.require(repo), parse_tasks(tasks_file(repo)))
    assert "<script>" not in page and "&lt;script&gt;" in page


def test_dashboard_never_breaks_a_save(repo: Path, cfg: config.Config) -> None:
    _start(cfg)
    tasks_file(repo).write_text("broken\n")
    run_state.halt(repo, run_state.require(repo), "still saved")
    assert run_state.load(repo)["halted"] == "still saved"  # type: ignore[index]


def test_cli_statusline_and_dashboard(
    repo: Path,
    cfg: config.Config,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"workspace": {"project_dir": str(repo)}}))
    )
    assert main(["statusline"]) == 0 and capsys.readouterr().out == "\n"  # no run yet
    _start(cfg)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert main(["statusline"]) == 0
    assert capsys.readouterr().out.startswith("SDD 009")
    assert main(["dashboard"]) == 0
    assert capsys.readouterr().out.strip().endswith(".sdd/dashboard.html")


def test_enable_statusline_is_opt_in_and_keeps_an_existing_one(tmp_path: Path) -> None:
    assert "enabled" in enable_statusline(tmp_path)
    local = json.loads((tmp_path / ".claude" / "settings.local.json").read_text())
    assert local["statusLine"]["command"] == "bash .sdd/bin/sdd statusline"
    assert "kept the existing" in enable_statusline(tmp_path)


def test_cli_init_with_statusline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert main(["init", "--statusline"]) == 0
    assert "status line enabled" in capsys.readouterr().out
