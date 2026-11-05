import json
import subprocess
from pathlib import Path

import pytest

from specsteward import prereqs
from specsteward.__main__ import main
from specsteward.doctor import FAIL, run_doctor
from specsteward.init import init_project


@pytest.fixture
def home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(prereqs.Path, "home", lambda: home)
    monkeypatch.setenv("TELEGRAM_STATE_DIR", str(home / "telegram"))
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    return home


@pytest.fixture
def no_tools(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A machine with nothing on PATH except what a test adds to the dict."""
    tools: dict[str, str] = {}
    monkeypatch.setattr(prereqs.shutil, "which", lambda name: tools.get(name))
    return tools


class Recorder:
    def __init__(self, result: int = 0, creates: Path | None = None) -> None:
        self.result, self.creates, self.calls = result, creates, []  # type: ignore[var-annotated]

    def __call__(self, cmd: list[str]) -> int:
        self.calls.append(cmd)
        if self.result == 0 and self.creates is not None:
            self.creates.parent.mkdir(parents=True, exist_ok=True)
            self.creates.write_text("")
        return self.result


FAKE_SCRIPT = b"# installer\n"
REAL_SHA256 = dict(prereqs.SCRIPT_SHA256)  # captured before the autouse stand-in below


def _fetch_ok(url: str, target: Path) -> None:
    target.write_bytes(FAKE_SCRIPT)


@pytest.fixture(autouse=True)
def fake_script_is_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests download FAKE_SCRIPT, so it stands in for the pinned official scripts."""
    import hashlib

    digest = hashlib.sha256(FAKE_SCRIPT).hexdigest()
    monkeypatch.setattr(prereqs, "SCRIPT_SHA256", {"install.sh": digest, "install.ps1": digest})


def test_a_script_that_does_not_match_its_checksum_never_runs(
    home: Path, no_tools: dict[str, str]
) -> None:
    no_tools.update(bash="bash", unzip="unzip")

    def tampered(url: str, target: Path) -> None:
        target.write_bytes(b"echo not the script we pinned\n")

    run = Recorder(creates=home / ".bun" / "bin" / "bun")
    ok, message = prereqs.install_bun("linux", run, tampered)
    assert not ok and "does not match its pinned checksum" in message and run.calls == []


def test_scripts_come_from_the_pinned_release_tag(home: Path, no_tools: dict[str, str]) -> None:
    no_tools.update(bash="bash", unzip="unzip")
    urls: list[str] = []

    def record(url: str, target: Path) -> None:
        urls.append(url)
        _fetch_ok(url, target)

    prereqs.install_bun("linux", Recorder(creates=home / ".bun" / "bin" / "bun"), record)
    assert urls == [
        f"https://raw.githubusercontent.com/oven-sh/bun/bun-v{prereqs.BUN_VERSION}"
        "/src/runtime/cli/install.sh"
    ]


def test_real_pins_are_sha256_hex() -> None:
    assert set(REAL_SHA256) == {"install.sh", "install.ps1"}
    assert all(len(h) == 64 and int(h, 16) >= 0 for h in REAL_SHA256.values())


def test_find_bun_on_path_or_in_the_user_folder(home: Path, no_tools: dict[str, str]) -> None:
    assert prereqs.find_bun() is None
    (home / ".bun" / "bin").mkdir(parents=True)
    (home / ".bun" / "bin" / "bun").write_text("")
    assert prereqs.find_bun() == str(home / ".bun" / "bin" / "bun")
    assert not prereqs.bun_on_path()
    no_tools["bun"] = "/usr/local/bin/bun"
    assert prereqs.find_bun() == "/usr/local/bin/bun" and prereqs.bun_on_path()


def test_phone_control_configured(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert not prereqs.phone_control_configured()
    (home / "telegram").mkdir()
    (home / "telegram" / ".env").write_text("TELEGRAM_BOT_TOKEN=x\n")
    assert prereqs.phone_control_configured()
    (home / "telegram" / ".env").unlink()
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "x")
    assert prereqs.phone_control_configured()


def test_package_managers_per_platform(no_tools: dict[str, str]) -> None:
    assert prereqs.package_manager_command("darwin") is None
    no_tools.update(brew="brew", winget="winget")
    assert prereqs.package_manager_command("darwin") == ["brew", "install", "oven-sh/bun/bun"]
    winget = prereqs.package_manager_command("win32")
    assert winget is not None and winget[:4] == ["winget", "install", "--id", "Oven-sh.Bun"]
    assert prereqs.package_manager_command("linux") is None  # no sudo package installs


def test_already_installed_is_a_no_op(home: Path, no_tools: dict[str, str]) -> None:
    no_tools["bun"] = "bun"
    run = Recorder()
    assert prereqs.install_bun("linux", run, _fetch_ok) == (True, "Bun is already installed")
    assert run.calls == []


def test_package_manager_is_tried_first(home: Path, no_tools: dict[str, str]) -> None:
    no_tools["brew"] = "brew"
    run = Recorder(creates=home / ".bun" / "bin" / "bun")
    ok, message = prereqs.install_bun("darwin", run, _fetch_ok)
    assert ok and message == "installed Bun with brew" and len(run.calls) == 1


def test_official_script_with_pinned_version_on_linux(home: Path, no_tools: dict[str, str]) -> None:
    no_tools.update(bash="bash", unzip="unzip")
    run = Recorder(creates=home / ".bun" / "bin" / "bun")
    ok, message = prereqs.install_bun("linux", run, _fetch_ok)
    assert ok and "Bun 1.4.4" in message and "restart your terminal" in message
    assert run.calls[0][0] == "bash" and run.calls[0][-1] == f"bun-v{prereqs.BUN_VERSION}"


def test_official_script_on_windows_without_winget(home: Path, no_tools: dict[str, str]) -> None:
    run = Recorder(creates=home / ".bun" / "bin" / "bun.exe")
    ok, _ = prereqs.install_bun("win32", run, _fetch_ok)
    cmd = run.calls[0]
    assert ok and cmd[0] == "powershell" and cmd[-2:] == ["-Version", prereqs.BUN_VERSION]
    assert "-File" in cmd  # runs the checksum-verified file it saved, not piped text


def test_missing_unzip_is_reported_not_sudo_installed(home: Path, no_tools: dict[str, str]) -> None:
    no_tools["bash"] = "bash"
    ok, message = prereqs.install_bun("linux", Recorder(), _fetch_ok)
    assert not ok and "unzip" in message and "apt install unzip" in message


def test_failures_are_reported(home: Path, no_tools: dict[str, str]) -> None:
    no_tools.update(bash="bash", unzip="unzip")
    ok, message = prereqs.install_bun("linux", Recorder(result=1), _fetch_ok)
    assert not ok and "installer failed" in message

    def offline(url: str, target: Path) -> None:
        raise OSError("network down")

    ok, message = prereqs.install_bun("linux", Recorder(), offline)
    assert not ok and "could not download" in message
    ok, message = prereqs.install_bun("linux", Recorder(result=0), _fetch_ok)  # no bun after
    assert not ok and "not found" in message


def test_downloads_only_from_bun_sh(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="refusing"):
        prereqs._fetch("https://example.com/install", tmp_path / "x")


def test_background_install_only_when_phone_control_needs_it(
    home: Path, no_tools: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    real_start = prereqs._real_bun_start  # type: ignore[attr-defined]  # saved by conftest
    spawned: list[dict[str, object]] = []
    monkeypatch.setattr(prereqs.subprocess, "Popen", lambda *a, **kw: spawned.append(kw))
    monkeypatch.setattr(prereqs.shutil, "which", lambda name: None)
    monkeypatch.setattr(prereqs.Path, "home", lambda: home)
    assert real_start(Path("entry.py")) is False  # no Telegram
    (home / "telegram").mkdir()
    (home / "telegram" / "access.json").write_text(json.dumps({"allowFrom": ["1"]}))
    assert real_start(Path("entry.py")) is True
    assert real_start(Path("entry.py")) is False  # once a day
    assert len(spawned) == 1 and spawned[0]["stdin"] == subprocess.DEVNULL
    assert spawned[0]["cwd"] == home


def test_cli_install_bun(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(prereqs, "install_bun", lambda: (True, "Bun is already installed"))
    assert main(["install", "bun"]) == 0
    assert "already installed" in capsys.readouterr().out


def test_doctor_requires_bun_once_phone_control_is_set_up(
    tmp_path: Path, home: Path, no_tools: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    init_project(tmp_path, "generic")
    assert not any("Bun" in f.what for f in run_doctor(tmp_path))
    (home / "telegram").mkdir()
    (home / "telegram" / ".env").write_text("TELEGRAM_BOT_TOKEN=x\n")
    found = run_doctor(tmp_path)
    assert any(f.level == FAIL and "Bun is missing" in f.what for f in found)


def test_discord_setup_also_needs_bun(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_STATE_DIR", str(home / "discord"))
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    assert not prereqs.phone_control_configured()
    (home / "discord").mkdir()
    (home / "discord" / ".env").write_text("DISCORD_BOT_TOKEN=x\n")
    assert prereqs.phone_control_configured()
