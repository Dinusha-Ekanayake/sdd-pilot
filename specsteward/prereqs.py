"""Prerequisites outside Python: Bun for phone control, plus checks for the rest.

Bun runs the official Telegram channel plugin's server (its ``.mcp.json`` starts ``bun``),
so it is needed only for phone control. specsteward installs it automatically when phone
control is set up (``/specsteward:remote``) or already configured, never otherwise:

- the OS package manager when there is one (Homebrew on macOS, winget on Windows);
- else Bun's official install script, downloaded over HTTPS from bun.sh into a temporary
  file (never piped into a shell) and run with a pinned version, from the home directory;
- never with sudo or administrator rights; it installs into ``~/.bun`` for this user.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

from specsteward.remote import state_dir
from specsteward.trust import user_dir

BUN_VERSION = "1.4.4"  # pinned; bump deliberately after checking the release notes
SCRIPT_UNIX = "https://bun.sh/install"
SCRIPT_WINDOWS = "https://bun.sh/install.ps1"
INSTALL_TIMEOUT = 10 * 60
RETRY_SECONDS = 24 * 60 * 60  # a failed background install is retried once a day

Runner = Callable[[list[str]], int]
Fetcher = Callable[[str, Path], None]


def _home_dir() -> Path:
    return user_dir()


def log_path() -> Path:
    return _home_dir() / "bun-install.log"


def _attempt_marker() -> Path:
    return _home_dir() / "bun-install.attempt"


def _run(cmd: list[str]) -> int:
    log_path().parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path().open("a", encoding="utf-8") as log:
            log.write(f"$ {' '.join(cmd)}\n")
            log.flush()
            return subprocess.run(
                cmd,
                cwd=Path.home(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=INSTALL_TIMEOUT,
            ).returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def _fetch(url: str, target: Path) -> None:
    if not url.startswith("https://bun.sh/"):
        raise ValueError(f"refusing to download an installer from {url}")
    with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed https URL
        target.write_bytes(response.read())


def find_bun() -> str | None:
    """``bun`` on PATH, or in ``~/.bun/bin`` (where the official script puts it)."""
    found = shutil.which("bun")
    if found:
        return found
    for name in ("bun.exe", "bun"):
        candidate = Path.home() / ".bun" / "bin" / name
        if candidate.is_file():
            return str(candidate)
    return None


def bun_on_path() -> bool:
    return shutil.which("bun") is not None


def phone_control_configured() -> bool:
    """The user has started Telegram setup: a token or a pairing exists."""
    directory = state_dir()
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN")) or any(
        (directory / name).exists() for name in (".env", "access.json")
    )


def package_manager_command(platform: str = sys.platform) -> list[str] | None:
    if platform == "darwin" and shutil.which("brew"):
        return ["brew", "install", "oven-sh/bun/bun"]
    if platform == "win32" and shutil.which("winget"):
        return [
            "winget", "install", "--id", "Oven-sh.Bun", "--exact", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
        ]  # fmt: skip
    return None


def _script(platform: str, fetch: Fetcher, run: Runner) -> tuple[bool, str]:
    """Download the official script to a temp file, then run it with the pinned version."""
    windows = platform == "win32"
    if not windows:
        missing = [tool for tool in ("bash", "unzip") if not shutil.which(tool)]
        if missing:
            hint = "for example `sudo apt install unzip`" if "unzip" in missing else ""
            return False, f"Bun's installer needs {', '.join(missing)}; install it ({hint})"
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / ("install.ps1" if windows else "install.sh")
        try:
            fetch(SCRIPT_WINDOWS if windows else SCRIPT_UNIX, script)
        except (OSError, ValueError) as error:
            return False, f"could not download Bun's installer: {error}"
        if windows:
            cmd = [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script), "-Version", BUN_VERSION,
            ]  # fmt: skip
        else:
            cmd = ["bash", str(script), f"bun-v{BUN_VERSION}"]
        if run(cmd) != 0:
            return False, f"Bun's installer failed; see {log_path()}"
    return True, f"installed Bun {BUN_VERSION} into ~/.bun"


def install_bun(
    platform: str = sys.platform, run: Runner = _run, fetch: Fetcher = _fetch
) -> tuple[bool, str]:
    """Install Bun for this user. Returns (ok, message)."""
    if find_bun():
        return True, "Bun is already installed"
    manager = package_manager_command(platform)
    if manager and run(manager) == 0 and find_bun():
        return True, f"installed Bun with {manager[0]}"
    ok, message = _script(platform, fetch, run)
    if ok and not find_bun():
        return False, f"Bun's installer finished but bun was not found; see {log_path()}"
    if ok and not bun_on_path():
        message += "; restart your terminal and Claude Code so `bun` is on PATH"
    return ok, message


def _recently_attempted() -> bool:
    try:
        return time.time() - _attempt_marker().stat().st_mtime < RETRY_SECONDS
    except OSError:
        return False


def start_background_bun_install(entry: Path) -> bool:
    """From SessionStart: install Bun in the background if phone control needs it."""
    if find_bun() or not phone_control_configured() or _recently_attempted():
        return False
    _attempt_marker().parent.mkdir(parents=True, exist_ok=True)
    _attempt_marker().write_text(str(time.time()), encoding="utf-8")
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        with log_path().open("a", encoding="utf-8") as log:
            subprocess.Popen(  # noqa: S603 - fixed argv: this interpreter and the plugin's entry
                [sys.executable, str(entry), "install", "bun"],
                cwd=Path.home(),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
                start_new_session=sys.platform != "win32",
                close_fds=True,
            )
    except OSError:
        return False
    return True
