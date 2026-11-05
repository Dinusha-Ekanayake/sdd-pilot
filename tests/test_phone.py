"""`sdd phone`: one-step setup, one bot per machine, and locking the bot to one account."""

import json
from pathlib import Path

import pytest

from specsteward import phone, prereqs
from specsteward.__main__ import main

TELEGRAM = phone.channel_named("telegram")
ID = "telegram@claude-plugins-official"


class FakeClaude:
    """Stands in for the `claude` CLI: a plugin list, and install/disable that change it."""

    def __init__(self, installed: bool = False, enabled: bool = True, fail: str = "") -> None:
        self.plugins = {ID: enabled} if installed else {}
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> tuple[int, str]:
        self.calls.append(args)
        if self.fail and self.fail in args:
            return 1, f"could not {self.fail}"
        if args[:2] == ["plugin", "list"]:
            entries = [{"id": i, "enabled": on, "scope": "user"} for i, on in self.plugins.items()]
            return 0, "noise before the json\n" + json.dumps(entries)
        if args[:2] == ["plugin", "install"]:
            self.plugins[args[2]] = True
            return 0, "installed"
        if args[:2] == ["plugin", "disable"]:
            self.plugins[args[2]] = False
            return 0, "disabled"
        return 1, "unexpected"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(phone.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(prereqs, "install_bun", lambda: (True, "Bun is already installed"))
    monkeypatch.setattr(phone, "launcher_dir", lambda: tmp_path / "bin")
    return tmp_path


def test_setup_installs_switches_off_and_writes_the_launcher(home: Path) -> None:
    claude = FakeClaude()
    ok, lines = phone.setup(TELEGRAM, claude)
    assert ok, lines
    assert ["plugin", "install", ID, "--scope", "user"] in claude.calls
    assert ["plugin", "disable", ID, "--scope", "user"] in claude.calls
    assert claude.plugins[ID] is False  # off in ordinary sessions: no competing bots
    script = (home / "bin" / "claude-phone").read_text(encoding="utf-8")
    assert "--channels plugin:telegram@claude-plugins-official" in script
    assert '--plugin-dir "$dir"' in script  # loaded for the phone session only


def test_setup_is_idempotent(home: Path) -> None:
    claude = FakeClaude(installed=True, enabled=False)
    ok, lines = phone.setup(TELEGRAM, claude)
    assert ok and not any(
        c[:2] in (["plugin", "install"], ["plugin", "disable"]) for c in claude.calls
    )
    assert "is off in ordinary sessions" in "\n".join(lines)


@pytest.mark.parametrize("step", ["install", "disable"])
def test_setup_reports_a_failing_step(home: Path, step: str) -> None:
    ok, lines = phone.setup(TELEGRAM, FakeClaude(installed=step == "disable", fail=step))
    assert not ok and lines[-1].startswith("FAIL")


def test_setup_stops_when_bun_cannot_be_installed(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(prereqs, "install_bun", lambda: (False, "needs unzip"))
    claude = FakeClaude()
    ok, lines = phone.setup(TELEGRAM, claude)
    assert not ok and "needs unzip" in lines[0] and claude.calls == []


def test_windows_gets_a_cmd_launcher_too(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(phone.sys, "platform", "win32")
    # shutil.which itself changes behaviour for "win32" on Python 3.12+; answer for it
    monkeypatch.setattr(phone.shutil, "which", lambda name: "C:/Program Files/Git/usr/bin/bash.exe")
    written = phone.write_launcher(TELEGRAM, home / "bin")
    assert [p.name for p in written] == ["claude-phone", "claude-phone.cmd"]
    cmd = (home / "bin" / "claude-phone.cmd").read_text(encoding="utf-8")
    assert cmd.startswith("@echo off") and '"%~dp0claude-phone" %*' in cmd
    assert "System32" not in cmd  # never WSL's bash


def test_plugin_state_handles_a_missing_or_broken_claude() -> None:
    assert phone.plugin_state(TELEGRAM, lambda args: (127, "not found")) is None
    assert phone.plugin_state(TELEGRAM, lambda args: (0, "no json here")) is None
    assert phone.enabled_everywhere(TELEGRAM, FakeClaude(installed=True)) is True
    assert phone.enabled_everywhere(TELEGRAM, FakeClaude(installed=True, enabled=False)) is False


def test_next_steps_are_specific_to_the_channel() -> None:
    assert "@BotFather" in "\n".join(phone.next_steps(TELEGRAM))
    discord = "\n".join(phone.next_steps(phone.channel_named("discord")))
    assert "Message Content Intent" in discord and "/discord:configure" in discord
    with pytest.raises(ValueError, match="channel must be one of"):
        phone.channel_named("slack")


# --- lock ---------------------------------------------------------------------------------


def _access(directory: Path, **data: object) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "access.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_lock_sets_allowlist_for_the_one_paired_account(tmp_path: Path) -> None:
    path = _access(tmp_path, dmPolicy="pairing", allowFrom=["42"], pending={})
    assert phone.lock(TELEGRAM, tmp_path) == "telegram locked: only account 42 can use the bot"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["dmPolicy"] == "allowlist" and data["pending"] == {}  # nothing else touched
    assert "already locked" in phone.lock(TELEGRAM, tmp_path)


@pytest.mark.parametrize("paired", [[], ["1", "2"]])
def test_lock_refuses_unless_exactly_one_account(tmp_path: Path, paired: list[str]) -> None:
    _access(tmp_path, dmPolicy="pairing", allowFrom=paired)
    with pytest.raises(ValueError, match="expected exactly one paired account"):
        phone.lock(TELEGRAM, tmp_path)


def test_lock_before_pairing_says_how_to_pair(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="/telegram:access pair"):
        phone.lock(TELEGRAM, tmp_path)


def test_cli_phone(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(phone, "setup", lambda channel: (True, ["ok   all set"]))
    assert main(["phone", "setup"]) == 0
    out = capsys.readouterr().out
    assert "ok   all set" in out and "claude-phone" in out
    monkeypatch.setenv("TELEGRAM_STATE_DIR", str(home / "tg"))
    _access(home / "tg", dmPolicy="pairing", allowFrom=["7"])
    assert main(["phone", "lock"]) == 0
    assert "locked" in capsys.readouterr().out


@pytest.mark.skipif(phone.shutil.which("bash") is None, reason="needs bash")
def test_launcher_loads_the_newest_plugin_and_turns_the_channel_on(tmp_path: Path) -> None:
    import os
    import subprocess

    config = tmp_path / "config"
    for version in ("0.0.7", "0.0.10"):  # sort -V: 0.0.10 is newer
        (config / "plugins" / "cache" / "claude-plugins-official" / "telegram" / version).mkdir(
            parents=True
        )
    bin_dir = tmp_path / "bin"
    phone.write_launcher(TELEGRAM, bin_dir)
    fake = bin_dir / "claude"  # records the arguments instead of starting Claude Code
    fake.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$@"\n', encoding="utf-8", newline="\n")
    fake.chmod(0o755)
    env = {**os.environ, "CLAUDE_CONFIG_DIR": config.as_posix()}
    env["PATH"] = bin_dir.as_posix() + os.pathsep + env.get("PATH", "")
    bash = str(phone.shutil.which("bash"))
    proc = subprocess.run(
        [bash, "-c", f'PATH="{bin_dir.as_posix()}:$PATH" bash claude-phone --resume'],
        cwd=bin_dir, capture_output=True, text=True, env=env, check=False,
    )  # fmt: skip
    args = proc.stdout.split("\n")
    assert proc.returncode == 0, proc.stderr
    assert args[0] == "--plugin-dir" and args[1].rstrip("/").endswith("telegram/0.0.10")
    assert args[2:5] == ["--channels", "plugin:telegram@claude-plugins-official", "--resume"]


@pytest.mark.skipif(phone.shutil.which("bash") is None, reason="needs bash")
def test_launcher_explains_a_missing_plugin(tmp_path: Path) -> None:
    import os
    import subprocess

    phone.write_launcher(TELEGRAM, tmp_path)
    env = {**os.environ, "CLAUDE_CONFIG_DIR": (tmp_path / "empty").as_posix()}
    bash = str(phone.shutil.which("bash"))
    proc = subprocess.run(
        [bash, str(tmp_path / "claude-phone")], capture_output=True, text=True, env=env, check=False
    )
    assert proc.returncode == 1 and "sdd phone setup" in proc.stderr
