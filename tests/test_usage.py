import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sdd_pilot import config, usage
from sdd_pilot import state as run_state
from sdd_pilot.dashboard import status_line
from sdd_pilot.tasks import parse_tasks

from .conftest import tasks_file, write_config

T0 = datetime(2026, 11, 4, 8, 0, tzinfo=UTC)


def _entry(message_id: str, when: datetime, inp: int = 10, out: int = 5, **extra: int) -> str:
    use = {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": 0}
    use |= {"cache_read_input_tokens": 0} | extra
    message = {"id": message_id, "usage": use}
    record = {"type": "assistant", "timestamp": when.isoformat(), "message": message}
    return json.dumps(record) + "\n"


def _session(tmp_path: Path) -> Path:
    main = tmp_path / "session.jsonl"
    (tmp_path / "session" / "subagents").mkdir(parents=True)
    main.write_text("")
    return main


def test_counts_each_response_once_and_only_after_the_run_started(tmp_path: Path) -> None:
    main = _session(tmp_path)
    late = T0 + timedelta(minutes=1)
    main.write_text(
        _entry("before", T0 - timedelta(minutes=1), inp=999)
        + _entry("m1", late) * 3  # one response, three content blocks
        + json.dumps({"type": "user", "message": {"content": "x"}})
        + "\n{not json\n"
        + _entry("m2", late, cache_read_input_tokens=1000)
    )
    totals = usage.collect(usage.empty(), str(main), T0)["totals"]
    assert totals["input_tokens"] == 20 and totals["output_tokens"] == 10
    assert usage.fresh(totals) == 30 and totals["cache_read_input_tokens"] == 1000


def test_subagent_transcripts_count_and_either_path_works(tmp_path: Path) -> None:
    main = _session(tmp_path)
    main.write_text(_entry("m1", T0))
    agent = tmp_path / "session" / "subagents" / "agent-1.jsonl"
    agent.write_text(_entry("a1", T0, inp=100))
    for given in (main, agent):
        assert usage.fresh(usage.collect(usage.empty(), str(given), T0)["totals"]) == 120


def test_reading_is_incremental_and_waits_for_whole_lines(tmp_path: Path) -> None:
    main = _session(tmp_path)
    main.write_text(_entry("m1", T0))
    first = usage.collect(usage.empty(), str(main), T0)
    with main.open("a") as handle:
        handle.write(_entry("m2", T0)[:-20])  # half-written by Claude Code
    second = usage.collect(first, str(main), T0)
    assert usage.fresh(second["totals"]) == 15
    with main.open("a") as handle:
        handle.write(_entry("m2", T0)[-20:])
    assert usage.fresh(usage.collect(second, str(main), T0)["totals"]) == 30


def test_a_replaced_transcript_is_read_from_the_start(tmp_path: Path) -> None:
    main = _session(tmp_path)
    main.write_text(_entry("m1", T0) * 1 + _entry("m2", T0))
    first = usage.collect(usage.empty(), str(main), T0)
    main.write_text(_entry("m3", T0))  # shorter than the stored offset
    assert usage.fresh(usage.collect(first, str(main), T0)["totals"]) == 45


def test_formatting() -> None:
    assert [usage.short(n) for n in (999, 12_345, 3_400_000)] == ["999", "12k", "3.4M"]
    totals = {"input_tokens": 1500, "output_tokens": 500, "cache_read_input_tokens": 2_000_000}
    assert usage.describe(totals) == "2k tokens (+2.0M cached reads)"


def test_run_tracks_usage_and_halts_over_budget(repo: Path, tmp_path: Path) -> None:
    cfg = write_config(repo, "[limits]\nmax_tokens = 100\n")
    run_state.start(cfg, "009", check_branch=False)
    main = _session(tmp_path)
    now = datetime.now(UTC) + timedelta(seconds=1)
    main.write_text(_entry("m1", now, inp=40, out=10))
    state = run_state.observe_usage(cfg, str(main))
    assert state is not None and state["halted"] is None
    assert "Used: 50 tokens" in run_state.summary(repo)
    assert "50 tok" in status_line(state, parse_tasks(tasks_file(repo)))
    with main.open("a") as handle:
        handle.write(_entry("m2", now, inp=60, out=10))
    state = run_state.observe_usage(cfg, str(main))
    assert state is not None and state["halted"] == "token budget reached (120 of 100)"


def test_no_budget_and_no_transcript_are_fine(cfg: config.Config, tmp_path: Path) -> None:
    assert run_state.observe_usage(cfg, str(tmp_path / "x.jsonl")) is None  # no run
    run_state.start(cfg, "009", check_branch=False)
    assert run_state.observe_usage(cfg, None) is None
    state = run_state.observe_usage(cfg, str(tmp_path / "missing.jsonl"))
    assert state is not None and state["halted"] is None


def test_max_tokens_must_not_be_negative(repo: Path) -> None:
    with pytest.raises(ValueError, match="max_tokens"):
        write_config(repo, "[limits]\nmax_tokens = -1\n")


def test_stop_hook_feeds_the_meter(
    repo: Path, cfg: config.Config, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    from sdd_pilot.__main__ import main

    run_state.start(cfg, "009", check_branch=False)
    transcript = _session(tmp_path)
    transcript.write_text(_entry("m1", datetime.now(UTC) + timedelta(seconds=1)))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"transcript_path": str(transcript)})))
    assert main(["hook-subagent-stop"]) == 0
    totals = run_state.require(repo)["usage"]["totals"]
    assert usage.fresh(totals) == 15
