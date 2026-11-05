"""Bot tokens in the operating system's credential store instead of a plain-text file.

- Windows: DPAPI, so the blob on disk can only be decrypted by this Windows user account.
- macOS: the login Keychain (the `security` tool).
- Linux: the Secret Service (GNOME Keyring, KWallet) through `secret-tool`.

`claude-phone` reads the token when it starts and hands it to Claude Code as an environment
variable. The channel plugin prefers that over its `.env` file (verified live: plugin
servers inherit Claude Code's environment), so no plain-text copy is needed. Credential
tools such as aws-vault work the same way. Where no credential store works (a headless Linux
box without a keyring), the caller falls back to the owner-only `.env` file and says so.

A small marker file records which store holds a channel's token. It holds no secret, and
lets status checks know a token exists without unlocking anything.
"""

import base64
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from specsteward.trust import user_dir

ACCOUNT = "bot-token"
TIMEOUT = 20
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.:-]+$")  # also keeps the `security -i` line well formed
LABELS = {
    "dpapi": "Windows DPAPI (only your Windows account can decrypt it)",
    "keychain": "the macOS Keychain",
    "secret-service": "your desktop keyring (Secret Service)",
}

# (command, text for stdin or None) -> (exit code, stdout)
Run = Callable[[list[str], str | None], tuple[int, str]]


def _run(args: list[str], stdin: str | None) -> tuple[int, str]:
    try:
        proc = subprocess.run(  # noqa: S603 - fixed system tools, no shell
            args,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return proc.returncode, proc.stdout


def service(name: str) -> str:
    return f"specsteward.{name}"


def secrets_dir() -> Path:
    return user_dir() / "secrets"


def _marker(name: str) -> Path:
    return secrets_dir() / f"{name}.store"


def blob_path(name: str) -> Path:
    return secrets_dir() / f"{name}.dpapi"


def backend(platform: str = sys.platform) -> str:
    """The credential store this machine offers, or "file" when there is none."""
    if platform == "win32":
        return "dpapi"
    if platform == "darwin" and shutil.which("security"):
        return "keychain"
    if platform.startswith("linux") and shutil.which("secret-tool"):
        return "secret-service"
    return "file"


def write_private(path: Path, text: str) -> None:
    """Replace ``path`` atomically with a file only its owner can read, from creation on."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, path)


# --- Windows DPAPI ------------------------------------------------------------------------


def _dpapi(data: bytes, protect: bool) -> bytes:
    """CryptProtectData / CryptUnprotectData for the current user, no UI."""
    if sys.platform != "win32":
        raise OSError("DPAPI is only on Windows")
    import ctypes
    import ctypes.wintypes as wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buffer = ctypes.create_string_buffer(data, len(data))
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    ui_forbidden = 0x1
    if not call(ctypes.byref(source), None, None, None, None, ui_forbidden, ctypes.byref(result)):
        raise OSError(f"DPAPI failed (error {ctypes.get_last_error()})")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        ctypes.WinDLL("kernel32").LocalFree(result.pbData)


# --- store and load -----------------------------------------------------------------------


def store(name: str, token: str, run: Run = _run, kind: str | None = None) -> str | None:
    """Save ``token`` in the credential store. Returns the store used, or None when there is
    none that works here (the caller then keeps the owner-only file)."""
    if not SAFE_TOKEN.match(token):
        raise ValueError("unexpected characters in the token")
    kind = kind or backend()
    try:
        if kind == "dpapi":
            blob = _dpapi(token.encode(), protect=True)
            write_private(blob_path(name), base64.b64encode(blob).decode() + "\n")
        elif kind == "keychain":
            line = f'add-generic-password -U -s "{service(name)}" -a "{ACCOUNT}" -w "{token}"\n'
            run(["security", "-i"], line)  # through stdin: never on a command line
        elif kind == "secret-service":
            label = f"specsteward {name} bot token"
            args = ["secret-tool", "store", f"--label={label}", "service", service(name)]
            run([*args, "account", ACCOUNT], token)
        else:
            return None
    except OSError:
        return None
    write_private(_marker(name), kind + "\n")
    if load(name, run) != token:  # read it back: a locked or missing keyring fails here
        forget(name)
        return None
    return kind


def stored_in(name: str) -> str:
    """Which store holds this channel's token ("" if none). Opens nothing."""
    try:
        return _marker(name).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def load(name: str, run: Run = _run) -> str:
    kind = stored_in(name)
    if kind == "dpapi":
        try:
            blob = base64.b64decode(blob_path(name).read_text(encoding="utf-8").strip())
            return _dpapi(blob, protect=False).decode()
        except (OSError, ValueError):
            return ""
    if kind == "keychain":
        args = ["security", "find-generic-password", "-s", service(name), "-a", ACCOUNT, "-w"]
    elif kind == "secret-service":
        args = ["secret-tool", "lookup", "service", service(name), "account", ACCOUNT]
    else:
        return ""
    code, out = run(args, None)
    return out.strip() if code == 0 else ""


def forget(name: str) -> None:
    """Drop the marker and the Windows blob (keyring entries are replaced on the next store)."""
    for path in (_marker(name), blob_path(name)):
        path.unlink(missing_ok=True)


# What `claude-phone` runs to read the token back. Kept here, next to the code that stores
# it, so both sides use the same service names. No single quotes inside: the launcher puts
# each one in a single-quoted bash string.
POWERSHELL_READ = (
    "Add-Type -AssemblyName System.Security; "
    "$t = Get-Content -Raw -LiteralPath $env:SPECSTEWARD_BLOB; "
    "$b = [Convert]::FromBase64String($t.Trim()); "
    "[Console]::Out.Write([Text.Encoding]::UTF8.GetString("
    "[Security.Cryptography.ProtectedData]::Unprotect("
    "$b, $null, [Security.Cryptography.DataProtectionScope]::CurrentUser)))"
)
