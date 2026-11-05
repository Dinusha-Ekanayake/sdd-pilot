"""Bot tokens in the OS credential store, and `claude-phone` handing them to the plugin."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from specsteward import check, doctor, phone, remote, secret_store, wizard

TOKEN = "123456789:" + "C" * 35
TELEGRAM = phone.channel_named("telegram")
HAS_BASH = phone.shutil.which("bash") is not None


class FakeTool:
    """`security` or `secret-tool`: remembers what was stored, records every call."""

    def __init__(self, works: bool = True) -> None:
        self.value = ""
        self.works = works
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args: list[str], stdin: str | None) -> tuple[int, str]:
        self.calls.append((args, stdin))
        if args[:2] == ["security", "-i"] and self.works:
            self.value = (stdin or "").split('-w "')[1].split('"')[0]
        elif args[:2] == ["secret-tool", "store"] and self.works:
            self.value = stdin or ""
        elif args[:2] in (["security", "find-generic-password"], ["secret-tool", "lookup"]):
            return (0, self.value + "\n") if self.value else (44, "")
        return 0, ""


@pytest.mark.parametrize("kind", ["keychain", "secret-service"])
def test_store_and_load_keep_the_token_off_command_lines(kind: str) -> None:
    tool = FakeTool()
    assert secret_store.store("telegram", TOKEN, tool, kind) == kind
    assert secret_store.stored_in("telegram") == kind
    assert secret_store.load("telegram", tool) == TOKEN
    for args, _stdin in tool.calls:
        assert TOKEN not in " ".join(args)  # visible to `ps`; only stdin carries it


def test_a_store_that_does_not_keep_the_token_is_not_used() -> None:
    tool = FakeTool(works=False)  # e.g. a locked keyring: store "succeeds", lookup fails
    assert secret_store.store("telegram", TOKEN, tool, "secret-service") is None
    assert secret_store.stored_in("telegram") == ""


def test_no_store_and_odd_tokens() -> None:
    assert secret_store.store("telegram", TOKEN, FakeTool(), "file") is None
    with pytest.raises(ValueError, match="unexpected characters"):
        secret_store.store("telegram", 'x" -w "y', FakeTool(), "keychain")
    assert secret_store.load("telegram", FakeTool()) == ""


def test_backend_by_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(secret_store.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert secret_store.backend("win32") == "dpapi"
    assert secret_store.backend("darwin") == "keychain"
    assert secret_store.backend("linux") == "secret-service"
    monkeypatch.setattr(secret_store.shutil, "which", lambda name: None)
    assert secret_store.backend("linux") == "file"


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is Windows only")
def test_dpapi_round_trip_and_no_plain_text_on_disk() -> None:
    assert secret_store.store("telegram", TOKEN) == "dpapi"
    assert TOKEN not in secret_store.blob_path("telegram").read_text(encoding="utf-8")
    assert secret_store.load("telegram") == TOKEN
    secret_store.forget("telegram")
    assert secret_store.load("telegram") == ""


# --- claude-phone reads it back -----------------------------------------------------------


def _launch(tmp_path: Path, tools: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the real launcher with stand-in tools; the fake `claude` prints the token."""
    config = tmp_path / "config"
    (config / "plugins" / "cache" / "claude-plugins-official" / "telegram" / "0.0.7").mkdir(
        parents=True
    )
    bin_dir = tmp_path / "bin"
    phone.write_launcher(TELEGRAM, bin_dir)
    tools = {"claude": 'printf "token=%s\\n" "${TELEGRAM_BOT_TOKEN:-}"', **tools}
    for name, body in tools.items():
        tool = bin_dir / name
        tool.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8", newline="\n")
        tool.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if key != "TELEGRAM_BOT_TOKEN"}
    env["CLAUDE_CONFIG_DIR"] = config.as_posix()
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")  # bash converts it
    bash = str(phone.shutil.which("bash"))
    return subprocess.run(
        [bash, str(bin_dir / "claude-phone")], capture_output=True, text=True, env=env, check=False
    )


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
@pytest.mark.parametrize(
    ("kind", "tool"), [("keychain", "security"), ("secret-service", "secret-tool")]
)
def test_launcher_passes_the_stored_token_to_the_session(
    tmp_path: Path, kind: str, tool: str
) -> None:
    secret_store.write_private(secret_store.secrets_dir() / "telegram.store", kind + "\n")
    proc = _launch(tmp_path, {tool: f'echo "{TOKEN}"'})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"token={TOKEN}"


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
def test_launcher_stops_when_the_store_cannot_be_read(tmp_path: Path) -> None:
    secret_store.write_private(secret_store.secrets_dir() / "telegram.store", "keychain\n")
    proc = _launch(tmp_path, {"security": "exit 44"})  # locked or deleted entry
    assert proc.returncode == 1 and "credential store" in proc.stderr and proc.stdout == ""


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
def test_launcher_without_a_store_leaves_the_plugin_its_own_file(tmp_path: Path) -> None:
    proc = _launch(tmp_path, {})
    assert proc.returncode == 0 and proc.stdout.strip() == "token="


@pytest.mark.skipif(sys.platform != "win32" or not HAS_BASH, reason="DPAPI is Windows only")
def test_launcher_decrypts_dpapi_with_powershell(tmp_path: Path) -> None:
    assert secret_store.store("telegram", TOKEN) == "dpapi"
    proc = _launch(tmp_path, {})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == f"token={TOKEN}"


# --- everything else knows about it -------------------------------------------------------


def test_checks_never_see_the_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "d")
    env = check.without_bot_tokens()
    assert "TELEGRAM_BOT_TOKEN" not in env and "DISCORD_BOT_TOKEN" not in env
    assert env.get("PATH") == os.environ.get("PATH")


def test_a_stored_token_counts_as_set(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_STATE_DIR", str(tmp_path / "tg"))
    assert not remote.configured(TELEGRAM)
    secret_store.write_private(secret_store.secrets_dir() / "telegram.store", "dpapi\n")
    assert remote.configured(TELEGRAM)
    assert remote.channel_status(TELEGRAM)["token_set"] is True


def test_doctor_warns_about_a_plain_text_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TELEGRAM_STATE_DIR", str(tmp_path / "tg"))
    monkeypatch.setenv("DISCORD_STATE_DIR", str(tmp_path / "dc"))
    wizard.write_token(tmp_path / "tg" / ".env", "TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(doctor, "running_servers", lambda: {})
    monkeypatch.setattr(doctor.phone, "enabled_everywhere", lambda channel: False)
    monkeypatch.setattr(secret_store, "backend", lambda: "keychain")
    found = [f for f in doctor._remote() if "plain-text" in f.what]
    assert found and "macOS Keychain" in found[0].fix
    monkeypatch.setattr(secret_store, "backend", lambda: "file")
    assert not [f for f in doctor._remote() if "plain-text" in f.what]


@pytest.mark.skipif(
    sys.platform != "darwin" or not os.environ.get("CI"), reason="real Keychain, CI runner only"
)
def test_real_macos_keychain_round_trip() -> None:
    name = f"ci-{os.getpid()}"
    try:
        assert secret_store.store(name, TOKEN) == "keychain"
        assert secret_store.load(name) == TOKEN
    finally:
        subprocess.run(
            ["security", "delete-generic-password", "-s", secret_store.service(name)],
            capture_output=True, check=False,
        )  # fmt: skip
