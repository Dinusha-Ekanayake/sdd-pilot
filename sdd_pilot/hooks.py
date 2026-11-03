"""Claude Code hooks. All of them do nothing in a project without ``sdd.toml``."""

import shlex
import subprocess
from pathlib import Path
from typing import Any

from sdd_pilot import state as run_state
from sdd_pilot import trust
from sdd_pilot.check import resolve_cmd
from sdd_pilot.config import Config
from sdd_pilot.tasks import parse_tasks

SHIM = Path(".sdd") / "bin" / "sdd"
SDD = f"bash {SHIM.as_posix()}"
CONTINUE_REASON = (
    "SDD run for spec {spec}: {open} task(s) still open. Run `{sdd} next` and continue "
    'the /sdd-pilot:run loop. If you need the user, run `{sdd} halt "<reason>"` first, '
    "then ask."
)
SESSION_CONTEXT = (
    "sdd-pilot is active in this project. Run its CLI as `{sdd} <command>` from the "
    "repository root (no `cd` prefix). `{sdd} status` shows the current run."
)


def stop_decision(cfg: Config) -> dict[str, str] | None:
    """Block the stop while tasks remain, but only if a task was completed since the last block.

    No progress since the last automatic continue halts the run, so it can never loop forever.
    """
    state = run_state.load(cfg.root)
    if state is None or not state["active"] or state["halted"]:
        return None
    tasks = parse_tasks(run_state.tasks_path(cfg.root, state))
    open_count = sum(t.pending for t in tasks)
    if open_count == 0:
        return None
    done = len(tasks) - open_count
    if done <= state["last_block_done"]:
        run_state.halt(cfg.root, state, "no task completed since the last automatic continue")
        return None
    state["last_block_done"] = done
    run_state.save(cfg.root, state)
    reason = CONTINUE_REASON.format(spec=state["spec"], open=open_count, sdd=SDD)
    return {"decision": "block", "reason": reason}


GUARD_REASON = (
    "sdd-pilot: {path} is run state or the trust store. It is written only by the sdd CLI, "
    "so gates and caps cannot be edited around. Use `{sdd} <command>` instead."
)


def _edited_path(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input") or {}
    return str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")


def _inside(path: Path, directory: Path) -> bool:
    try:
        return path.is_relative_to(directory.resolve())
    except (OSError, ValueError):
        return False


def guard_decision(cfg: Config, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Deny file-tool edits to ``.sdd/`` and to the trust store (PreToolUse)."""
    raw = _edited_path(payload)
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = Path(str(payload.get("cwd") or cfg.root)) / path
    path = path.resolve()
    protected = (cfg.root / SHIM.parent.parent, trust.store_path().parent)
    if not any(_inside(path, directory) for directory in protected):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": GUARD_REASON.format(path=raw, sdd=SDD),
        }
    }


def format_file(cfg: Config, payload: dict[str, Any]) -> None:
    """Run the configured formatters on an edited file. Never fails the edit.

    Does nothing until the user has trusted this exact ``sdd.toml``: the commands come
    from the repository, and this hook runs without a permission prompt.
    """
    if not trust.config_trusted(cfg.root):
        return
    file_path = str(payload.get("tool_input", {}).get("file_path", ""))
    path = Path(file_path)
    if not file_path or not path.exists():
        return
    for cmd in cfg.format_cmds.get(path.suffix, ()):
        args = [part.replace("{file}", file_path) for part in cmd]
        try:
            subprocess.run(
                resolve_cmd(tuple(args), cfg.root),
                cwd=cfg.root,
                capture_output=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue


def write_shim(root: Path, launcher: Path) -> Path:
    """``.sdd/bin/sdd`` points at this plugin version, so permission rules stay stable."""
    shim = root / SHIM
    shim.parent.mkdir(parents=True, exist_ok=True)
    target = shlex.quote(launcher.as_posix())
    shim.write_text(
        f'#!/usr/bin/env bash\nexec bash {target} "$@"\n', encoding="utf-8", newline="\n"
    )
    return shim


def session_context() -> str:
    return SESSION_CONTEXT.format(sdd=SDD)
