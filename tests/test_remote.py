"""Phone control over either official channel plugin."""

import json
from pathlib import Path

import pytest

from specsteward import remote

READY = {"dmPolicy": "allowlist", "allowFrom": ["42"]}


@pytest.fixture
def channels(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    dirs = {}
    for channel in remote.CHANNELS:
        directory = tmp_path / channel.name
        monkeypatch.setenv(channel.dir_var, str(directory))
        monkeypatch.delenv(channel.token_var, raising=False)
        dirs[channel.name] = directory
    return dirs


def _ready(directory: Path, token_var: str) -> None:
    directory.mkdir()
    (directory / ".env").write_text(f"{token_var}=secret\n")
    (directory / "access.json").write_text(json.dumps(READY))


def test_nothing_set_up_defaults_to_telegram(channels: dict[str, Path]) -> None:
    status = remote.remote_status()
    assert status["channel"] == "telegram" and status["ready"] is False and status["others"] == []


def test_discord_alone_is_used(channels: dict[str, Path]) -> None:
    _ready(channels["discord"], "DISCORD_BOT_TOKEN")
    status = remote.remote_status()
    assert status["channel"] == "discord" and status["ready"] and status["chat_ids"] == ["42"]


def test_a_ready_channel_wins_over_a_half_set_up_one(channels: dict[str, Path]) -> None:
    channels["telegram"].mkdir()
    (channels["telegram"] / ".env").write_text("TELEGRAM_BOT_TOKEN=x\n")  # not paired yet
    _ready(channels["discord"], "DISCORD_BOT_TOKEN")
    status = remote.remote_status()
    assert status["channel"] == "discord" and status["others"] == ["telegram"]


def test_discord_problems_name_its_own_commands(channels: dict[str, Path]) -> None:
    discord = remote.CHANNELS[1]
    channels["discord"].mkdir()
    access = {"dmPolicy": "pairing", "allowFrom": ["1"], "groups": {"9": {}}}
    (channels["discord"] / "access.json").write_text(json.dumps(access))
    problems = " | ".join(remote.channel_status(discord)["problems"])
    assert (
        "phone setup --channel discord" in problems
        and "/discord:access policy allowlist" in problems
    )
    assert "server channels" in problems
