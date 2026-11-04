"""Release hygiene, and the review fixes that keep a public install trouble-free."""

import json
import os
import re
import threading
import tomllib
from pathlib import Path

import pytest

from sdd_pilot import config, trust
from sdd_pilot.init import render_config
from sdd_pilot.remote import telegram_status

ROOT = Path(__file__).resolve().parent.parent


def test_versions_agree() -> None:
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    package = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    top = re.search(r"^## (\d+\.\d+\.\d+)", changelog, re.MULTILINE)
    assert top is not None
    assert plugin["version"] == package["project"]["version"] == top.group(1)


def test_generated_config_follows_the_plugins_graphify_pin(tmp_path: Path) -> None:
    (tmp_path / "sdd.toml").write_text(render_config(tmp_path, "generic"), encoding="utf-8")
    assert config.load(tmp_path).graphify_version == config.GRAPHIFY_VERSION


def test_concurrent_writers_do_not_lose_records(repo: Path) -> None:
    errors: list[BaseException] = []

    def approve(spec: str) -> None:
        try:
            trust.record_approval(repo, spec, f"hash-{spec}")
        except BaseException as error:  # noqa: BLE001 - surfaced by the assert below
            errors.append(error)

    threads = [threading.Thread(target=approve, args=(f"{n:03d}",)) for n in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert all(trust.approved_hash(repo, f"{n:03d}") == f"hash-{n:03d}" for n in range(20))


def test_a_stale_lock_from_a_killed_process_is_cleared(repo: Path) -> None:
    lock = trust.store_path().with_suffix(".lock")
    lock.write_text("")
    old = lock.stat().st_mtime - trust.STALE_LOCK - 1
    os.utime(lock, (old, old))
    trust.record_approval(repo, "010", "abc")
    assert trust.approved_hash(repo, "010") == "abc" and not lock.exists()


def test_a_held_lock_times_out_with_a_clear_error(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(trust, "LOCK_TIMEOUT", 0.1)
    trust.store_path().with_suffix(".lock").write_text("")
    with pytest.raises(ValueError, match="trust store is locked"):
        trust.record_approval(repo, "010", "abc")


@pytest.mark.parametrize(
    ("content", "expected"),
    [("", False), ("TELEGRAM_BOT_TOKEN=\n", False), ("TELEGRAM_BOT_TOKEN=123:abc\n", True)],
)
def test_bot_token_needs_a_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str, expected: bool
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    (tmp_path / ".env").write_text(content)
    assert telegram_status(tmp_path)["token_set"] is expected


def test_an_unreadable_store_is_never_saved_over_as_empty(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust.record_approval(repo, "010", "keep-me")
    store = trust.store_path()
    real_read = Path.read_text

    def locked(self: Path, *args: object, **kwargs: object) -> str:
        if self == store:
            raise PermissionError(13, "in use by another process")
        return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(trust, "RETRY_SECONDS", 0.1)
    monkeypatch.setattr(Path, "read_text", locked)
    with pytest.raises(ValueError, match="cannot read the trust store"):
        trust.record_approval(repo, "011", "new")
    monkeypatch.setattr(Path, "read_text", real_read)
    assert trust.approved_hash(repo, "010") == "keep-me"  # nothing was wiped


def test_a_brief_windows_sharing_clash_is_retried(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_replace = trust.os.replace
    clashes = [PermissionError(13, "sharing violation")] * 3

    def flaky(src: str, dst: str) -> None:
        if clashes:
            raise clashes.pop()
        real_replace(src, dst)

    monkeypatch.setattr(trust.os, "replace", flaky)
    trust.record_approval(repo, "012", "abc")
    assert trust.approved_hash(repo, "012") == "abc" and not clashes
