import json
import sys
from pathlib import Path

import pytest

from sdd_pilot.__main__ import main
from sdd_pilot.doctor import FAIL, OK, WARN, Finding, format_findings, run_doctor
from sdd_pilot.init import init_project

from .conftest import write_config


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path_factory.mktemp("home")
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("TELEGRAM_STATE_DIR", str(home / "telegram"))


def _levels(found: list[Finding]) -> dict[str, str]:
    return {item.what: item.level for item in found}


def test_without_config_doctor_points_to_init(tmp_path: Path) -> None:
    found = run_doctor(tmp_path)
    assert found[-1].level == FAIL and "init" in found[-1].fix


def test_fresh_init_is_healthy(tmp_path: Path) -> None:
    init_project(tmp_path, "generic")
    levels = _levels(run_doctor(tmp_path))
    assert FAIL not in levels.values()
    assert levels["no [[check]] steps"] == WARN
    assert levels["approve, trust, start and resume prompt you"] == OK


def test_untrusted_config_and_missing_tools_fail(repo: Path) -> None:
    (repo / "sdd.toml").write_text('[[check]]\nname = "t"\ncmd = ["no-such-tool-xyz"]\n')
    assert _levels(run_doctor(repo))["sdd.toml is not trusted"] == FAIL
    write_config(repo, '[[check]]\nname = "t"\ncmd = ["no-such-tool-xyz"]\n')
    found = run_doctor(repo)
    assert any(f.level == FAIL and "no-such-tool-xyz" in f.what for f in found)


def test_missing_gates_and_bypass_mode_fail(repo: Path) -> None:
    settings = repo / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}))
    found = run_doctor(repo)
    whats = {f.what for f in found if f.level == FAIL}
    assert "defaultMode is bypassPermissions" in whats
    assert any(what.startswith("sdd gates do not prompt") for what in whats)


def test_relaxed_git_rules_only_warn(tmp_path: Path) -> None:
    init_project(tmp_path, "generic")
    settings = tmp_path / ".claude" / "settings.json"
    data = json.loads(settings.read_text())
    data["permissions"]["ask"].remove("Bash(git commit:*)")
    settings.write_text(json.dumps(data))
    found = run_doctor(tmp_path)
    assert any(f.level == WARN and "git commit" in f.what for f in found)
    assert FAIL not in {f.level for f in found}


def test_check_steps_report_the_resolved_executable(repo: Path) -> None:
    write_config(repo, f'[[check]]\nname = "t"\ncmd = [{json.dumps(sys.executable)}]\n')
    assert _levels(run_doctor(repo))[f"check 't' runs {Path(sys.executable).name}"] == OK


def test_format_and_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text = format_findings([Finding(OK, "a", "unused"), Finding(WARN, "b", "do x")])
    assert text.splitlines() == [
        "ok   a",
        "warn b  -> do x",
        "SDD DOCTOR: OK (0 to fix, 1 warnings)",
    ]
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert main(["doctor"]) == 1  # no sdd.toml
    init_project(tmp_path, "generic")
    capsys.readouterr()
    assert main(["doctor", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["level"] == OK
