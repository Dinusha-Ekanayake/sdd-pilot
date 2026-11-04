"""Token usage of a run, read from Claude Code's transcripts, for a real budget.

Hooks receive ``transcript_path`` (the session's JSONL). Subagents write their own
transcripts in ``<session>/subagents/``. Each API response appears once per content block,
so usage is counted once per message id. Files are read incrementally from a stored byte
offset, and only responses after the run started count.

"Fresh" tokens (input, cache writes and output) are what ``[limits] max_tokens`` limits;
cache reads are reported separately because they cost about a tenth as much.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")
RECENT_IDS = 64  # one response's blocks sit close together; remember a few ids per file

Usage = dict[str, Any]


def empty() -> Usage:
    return {"totals": dict.fromkeys(KEYS, 0), "files": {}}


def fresh(totals: dict[str, int]) -> int:
    return (
        totals.get("input_tokens", 0)
        + totals.get("cache_creation_input_tokens", 0)
        + totals.get("output_tokens", 0)
    )


def transcripts(transcript_path: str) -> list[Path]:
    """The session transcript and its subagents' (given either kind of path)."""
    main = Path(transcript_path)
    if main.parent.name == "subagents":  # a subagent's own transcript was passed
        main = Path(f"{main.parent.parent}.jsonl")
    subagents = main.with_suffix("") / "subagents"
    found = [main] if main.is_file() else []
    if subagents.is_dir():
        found += sorted(subagents.glob("*.jsonl"))
    return found


def _after(timestamp: object, since: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(timestamp)) >= since
    except ValueError:
        return False


def _count(line: bytes, since: datetime, recent: list[str], totals: dict[str, int]) -> None:
    try:
        entry = json.loads(line)
    except ValueError:
        return
    message = entry.get("message") if isinstance(entry, dict) else None
    if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
        return
    message_id = str(message.get("id") or entry.get("requestId") or "")
    if not message_id or message_id in recent or not _after(entry.get("timestamp"), since):
        return
    recent.append(message_id)
    del recent[:-RECENT_IDS]
    for key in KEYS:
        value = message["usage"].get(key, 0)
        totals[key] += value if isinstance(value, int) else 0


def collect(usage: Usage, transcript_path: str, since: datetime) -> Usage:
    """Add what the transcripts gained since the last call; returns the updated usage."""
    totals = {key: int(usage["totals"].get(key, 0)) for key in KEYS}
    files: dict[str, Any] = dict(usage.get("files", {}))
    for path in transcripts(transcript_path):
        state = files.get(str(path), {"offset": 0, "recent": []})
        offset, recent = int(state["offset"]), list(state["recent"])
        try:
            with path.open("rb") as handle:
                if handle.seek(0, 2) < offset:
                    offset = 0  # the file was replaced
                handle.seek(offset)
                chunk = handle.read()
        except OSError:
            continue
        end = chunk.rfind(b"\n") + 1  # leave a half-written last line for next time
        for line in chunk[:end].splitlines():
            _count(line, since, recent, totals)
        files[str(path)] = {"offset": offset + end, "recent": recent}
    return {"totals": totals, "files": files}


def short(number: int) -> str:
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M"
    if number >= 1_000:
        return f"{number / 1_000:.0f}k"
    return str(number)


def describe(totals: dict[str, int]) -> str:
    reads = totals.get("cache_read_input_tokens", 0)
    return f"{short(fresh(totals))} tokens (+{short(reads)} cached reads)"
