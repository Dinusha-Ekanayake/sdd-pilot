"""Phone control through the official Telegram channel plugin.

sdd-pilot does not run its own bot. It reads the channel plugin's allowlist to know
which chat to notify, and checks that the setup is safe (allowlist policy, no
strangers). DM chat IDs equal the sender's user ID, so ``allowFrom`` is the chat list.
"""

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path.home() / ".claude" / "channels" / "telegram"


def state_dir() -> Path:
    return Path(os.environ.get("TELEGRAM_STATE_DIR") or DEFAULT_STATE_DIR)


def _token_in(env_file: Path) -> bool:
    """A non-empty ``TELEGRAM_BOT_TOKEN=`` line, not just an .env file that exists."""
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return any(
        line.strip().startswith("TELEGRAM_BOT_TOKEN=") and line.split("=", 1)[1].strip()
        for line in lines
    )


def telegram_status(directory: Path | None = None) -> dict[str, Any]:
    directory = directory or state_dir()
    access_file = directory / "access.json"
    token_set = bool(os.environ.get("TELEGRAM_BOT_TOKEN")) or _token_in(directory / ".env")
    if not access_file.exists():
        return {
            "channel": "telegram",
            "ready": False,
            "chat_ids": [],
            "problems": ["not paired yet: DM the bot, then /telegram:access pair <code>"],
            "token_set": token_set,
        }
    access = json.loads(access_file.read_text(encoding="utf-8"))
    chat_ids = [str(i) for i in access.get("allowFrom", [])]
    problems = []
    if not token_set:
        problems.append("no bot token: run /telegram:configure <token>")
    if not chat_ids:
        problems.append("allowlist is empty: pair your account first")
    if len(chat_ids) > 1:
        problems.append("more than one user can approve; keep only yours for gates")
    if access.get("dmPolicy", "pairing") != "allowlist":
        problems.append("dmPolicy is not 'allowlist': run /telegram:access policy allowlist")
    if access.get("groups"):
        problems.append("bot is in groups; gate messages go to DMs only")
    return {
        "channel": "telegram",
        "ready": not problems,
        "chat_ids": chat_ids,
        "problems": problems,
        "token_set": token_set,
    }
