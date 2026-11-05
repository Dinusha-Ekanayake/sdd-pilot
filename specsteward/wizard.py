"""`sdd phone setup` in a terminal: a guided setup that leaves only the steps a person must do.

Telegram: paste the token, send the bot one message, confirm it was you. The wizard saves
the token where the plugin reads it, writes your account to the allowlist and locks the
bot, sends a test message and can start `claude-phone`. Pairing is confirmed on your own
keyboard, never from a chat message. Discord: the token is checked and saved; pairing
still happens through the plugin, because reading Discord DMs needs a live gateway.
"""

import getpass
import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from specsteward import bots, phone
from specsteward.remote import Channel, running_servers, state_dir

PAIR_SECONDS = 180
TOKEN_ATTEMPTS = 3


class Console:
    """Terminal input and output; tests pass a scripted stand-in."""

    def say(self, text: str = "") -> None:
        print(text, flush=True)

    def secret(self, prompt: str) -> str:
        return getpass.getpass(prompt)

    def yes(self, question: str, default: bool) -> bool:
        hint = "[Y/n]" if default else "[y/N]"
        try:
            answer = input(f"{question} {hint} ").strip().lower()
        except EOFError:
            return default
        return default if not answer else answer in ("y", "yes")


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


# --- files the plugin reads ---------------------------------------------------------------


def read_token(env_file: Path, var: str) -> str:
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and key.strip() == var:
            return value.strip()
    return ""


def _replace(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(path.name + ".tmp")
    tmp.unlink(missing_ok=True)
    # Owner-only from the moment it exists: the token is a credential. It has to be stored
    # in plain text, because the official plugin reads it from this file (as
    # /<channel>:configure writes it).
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(tmp, path)


def write_token(env_file: Path, var: str, token: str) -> None:
    """Set ``VAR=token`` and keep any other lines."""
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    kept = [line for line in lines if line.partition("=")[0].strip() != var]
    _replace(env_file, "\n".join([*kept, f"{var}={token}"]) + "\n")


def _access(access_file: Path) -> dict[str, object]:
    try:
        data = json.loads(access_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def locked_account(access_file: Path) -> str:
    """The one account the bot is locked to, or ""."""
    access = _access(access_file)
    allowed = access.get("allowFrom")
    if access.get("dmPolicy") == "allowlist" and isinstance(allowed, list) and len(allowed) == 1:
        return str(allowed[0])
    return ""


def write_lock(access_file: Path, user_id: str) -> int:
    """Only ``user_id`` may use the bot. Keeps group settings; returns accounts removed."""
    access = _access(access_file)
    before = access.get("allowFrom")
    removed = len([i for i in before if str(i) != user_id]) if isinstance(before, list) else 0
    access.update(dmPolicy="allowlist", allowFrom=[user_id], pending={})
    access.setdefault("groups", {})
    _replace(access_file, json.dumps(access, indent=2) + "\n")
    return removed


# --- steps --------------------------------------------------------------------------------


def _bot_help(channel: Channel) -> list[str]:
    if channel.name == "telegram":
        return [
            "Create a bot: open https://t.me/BotFather in Telegram, send /newbot,",
            "pick a name and a username ending in 'bot', and copy the token it sends.",
        ]
    return [
        "Create a bot: https://discord.com/developers/applications -> New Application ->",
        "Bot -> Reset Token (copy it), and turn on Message Content Intent. Then invite it:",
        "OAuth2 -> URL Generator -> scope 'bot' -> open the URL.",
    ]


def _check(channel: Channel, token: str, telegram: Callable[[str], bots.Telegram]) -> str:
    if channel.name == "telegram":
        return telegram(token).username()
    return bots.discord_username(token)


def _token(
    channel: Channel, console: Console, telegram: Callable[[str], bots.Telegram]
) -> tuple[str, str] | None:
    """(token, bot username), saved where the plugin reads it, or None."""
    env_file = state_dir(channel) / ".env"
    existing = read_token(env_file, channel.token_var)
    if existing:
        try:
            name = _check(channel, existing, telegram)
        except bots.BotError as error:
            console.say(f"warn the saved token no longer works: {error}")
        else:
            if console.yes(f"Use the bot you already set up, @{name}?", True):
                return existing, name
    console.say()
    for line in _bot_help(channel):
        console.say(line)
    for _ in range(TOKEN_ATTEMPTS):
        token = console.secret("Paste the bot token (it stays hidden): ").strip()
        if not bots.valid_token(channel.name, token):
            console.say(f"That does not look like a {channel.name} bot token; try again.")
            continue
        try:
            name = _check(channel, token, telegram)
        except bots.BotError as error:
            console.say(f"FAIL {error}")
            continue
        write_token(env_file, channel.token_var, token)
        console.say(f"ok   connected to @{name}; token saved to {env_file}")
        return token, name
    console.say("FAIL no working token; run `sdd phone setup` again when you have one")
    return None


def _wait_for_you(
    api: bots.Telegram, bot: str, console: Console, clock: Callable[[], float]
) -> str | None:
    offset = api.skip_backlog()
    console.say()
    console.say(f"Now send any message to @{bot} in Telegram (waiting up to 3 minutes)...")
    deadline = clock() + PAIR_SECONDS
    while clock() < deadline:
        offset, sender = api.next_private_message(offset)
        if sender is None:
            continue
        preview = sender.text[:40]
        question = (
            f"Message from {sender.name}, account {sender.user_id}: {preview!r}. Is this you?"
        )
        if console.yes(question, False):
            api.acknowledge(offset)
            return sender.user_id
        console.say("Ignored. Waiting for your message...")
    api.acknowledge(offset)
    console.say("FAIL no message arrived; run `sdd phone setup` again")
    return None


def _pair_telegram(
    token: str,
    bot: str,
    console: Console,
    telegram: Callable[[str], bots.Telegram],
    clock: Callable[[], float],
) -> bool:
    access_file = state_dir(phone.channel_named("telegram")) / "access.json"
    locked = locked_account(access_file)
    if locked and console.yes(f"The bot is locked to account {locked}. Keep that?", True):
        return True
    api = telegram(token)
    try:
        user_id = _wait_for_you(api, bot, console, clock)
        if user_id is None:
            return False
        removed = write_lock(access_file, user_id)
        extra = f" ({removed} other account(s) removed)" if removed else ""
        console.say(f"ok   locked: only account {user_id} can use @{bot}{extra}")
        api.send(
            user_id,
            "specsteward connected. Start Claude Code with claude-phone, then send: "
            "status, approve <NNN>, answer: ..., resume, ship <NNN>, stop.",
        )
        console.say("ok   sent a test message to your phone")
    except bots.BotError as error:
        console.say(f"FAIL {error}")
        return False
    return True


def _old_copies(channel: Channel, console: Console) -> None:
    count = running_servers().get(channel.name, 0)
    if count:
        console.say(
            f"warn {count} copy(ies) of the {channel.name} bot still run in Claude Code "
            "windows opened before setup; close or restart those windows"
        )


def launch_phone() -> int:
    script = phone.launcher_dir() / phone.LAUNCHER
    bash = shutil.which("bash") or "bash"
    return subprocess.call([bash, str(script)])  # noqa: S603 - our own launcher


def run(
    channel: Channel,
    console: Console | None = None,
    *,
    telegram: Callable[[str], bots.Telegram] = bots.Telegram,
    launch: Callable[[], int] = launch_phone,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    console = console or Console()
    ok, lines = phone.setup(channel)
    for line in lines:
        console.say(line)
    if not ok:
        return 1
    _old_copies(channel, console)
    found = _token(channel, console, telegram)
    if found is None:
        return 1
    token, bot = found
    if channel.name == "telegram":
        if not _pair_telegram(token, bot, console, telegram, clock):
            return 1
    else:
        console.say()
        console.say("Last steps, in a `claude-phone` session: DM the bot, run")
        console.say(
            "/discord:access pair <code>, then `bash .sdd/bin/sdd phone lock --channel discord`."
        )
    console.say()
    if console.yes("Start phone control now (claude-phone)?", True):
        return launch()
    console.say(f"Start it any time with `{phone.LAUNCHER}` instead of `claude`.")
    return 0
