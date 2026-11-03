"""CLI: ``sdd <command>``. In a project, Claude runs it as ``bash .sdd/bin/sdd <command>``."""

import argparse
import io
import json
import os
import sys
from pathlib import Path

from sdd_pilot import config as cfg_mod
from sdd_pilot import state as run_state
from sdd_pilot import trust
from sdd_pilot.brief import write_brief
from sdd_pilot.check import format_report, run_all, signature
from sdd_pilot.hooks import (
    SDD,
    format_file,
    guard_decision,
    session_context,
    stop_decision,
    write_shim,
)
from sdd_pilot.init import PRESETS, init_project
from sdd_pilot.remote import telegram_status

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = PLUGIN_ROOT / "bin" / "sdd"
HOOKS = (
    "hook-stop",
    "hook-format",
    "hook-guard",
    "hook-subagent-stop",
    "hook-session-start",
)


def _start_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdd", description="Spec-driven runs for Claude Code")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="set up sdd.toml, templates and permissions")
    init.add_argument("--preset", choices=PRESETS, default="generic")
    init.add_argument("--specs-dir", default="specs")
    init.add_argument("--force", action="store_true")
    check = sub.add_parser("check", help="run the quality gate")
    check.add_argument(
        "--task", help="record failures for this task (default: the group in flight)"
    )
    brief = sub.add_parser("brief", help="write .sdd/briefs/<first-id>.md")
    brief.add_argument("tasks", nargs="+")
    start = sub.add_parser("start", help="start a run for an approved spec")
    start.add_argument("spec")
    start.add_argument("--no-branch-check", action="store_true")
    approve = sub.add_parser("approve", help="mark a spec approved (keep behind an ask rule)")
    approve.add_argument("spec")
    approve.add_argument("--via", default="terminal")
    approve.add_argument("--start", action="store_true", help="start the run right after")
    approve.add_argument("--no-branch-check", action="store_true")
    agent = sub.add_parser("agent", help="count a subagent run")
    agent.add_argument("role", choices=("planner", "implementer", "reviewer", "clerk"))
    agent.add_argument("--fresh", action="store_true")
    review = sub.add_parser("review")
    review.add_argument("task")
    review.add_argument("verdict", choices=("clean", "changes"))
    done = sub.add_parser("done")
    done.add_argument("task")
    done.add_argument("--human", action="store_true", help="mark [?]: needs sign-off")
    assume = sub.add_parser("assume")
    assume.add_argument("task")
    assume.add_argument("text")
    sub.add_parser("halt").add_argument("reason")
    status = sub.add_parser("status")
    status.add_argument("--json", action="store_true")
    sub.add_parser("trust", help="trust the current sdd.toml (keep behind an ask rule)")
    for name in ("next", "resume", "stop", "remote", *HOOKS):
        sub.add_parser(name)
    return parser


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):  # Windows consoles default to cp1252
            stream.reconfigure(encoding="utf-8", errors="replace")


def _hook(command: str) -> int:
    """Hooks never fail the session: outside an sdd project they do nothing."""
    try:
        cfg = cfg_mod.load(_start_dir())
    except (ValueError, OSError):
        return 0
    if command == "hook-stop":
        decision = stop_decision(cfg)
        if decision:
            print(json.dumps(decision))
    elif command == "hook-format":
        format_file(cfg, json.load(sys.stdin))
    elif command == "hook-subagent-stop":
        run_state.observe_agent(cfg)
    elif command == "hook-guard":
        guard = guard_decision(cfg, json.load(sys.stdin))
        if guard:
            print(json.dumps(guard))
    else:
        write_shim(cfg.root, LAUNCHER)
        context = {"hookEventName": "SessionStart", "additionalContext": session_context()}
        print(json.dumps({"hookSpecificOutput": context}))
    return 0


def _check(cfg: cfg_mod.Config, task: str | None) -> int:
    results = run_all(cfg)
    print(format_report(results))
    if all(r.ok for r in results):
        run_state.record_pass(cfg)
        return 0
    task = task or run_state.current_task(cfg)
    if task:
        state = run_state.record_failure(cfg, task, signature(results))
        if state["halted"]:
            print(f"HALTED: {state['halted']}")
    return 1


def _run_command(args: argparse.Namespace, cfg: cfg_mod.Config) -> int:
    root, command = cfg.root, args.command
    if command == "check":
        return _check(cfg, args.task)
    if command == "next":
        print(json.dumps(run_state.next_step(cfg)))
        return 0
    if command == "brief":
        spec_dir = root / run_state.require(root)["spec_dir"]
        print(write_brief(cfg, spec_dir, args.tasks, SDD).relative_to(root).as_posix())
        return 0
    if command == "approve":
        print(f"spec {args.spec}: {run_state.approve(cfg, args.spec, args.via)}")
        if args.start:  # one permission prompt for "approve and go", e.g. from a phone
            state = run_state.start(cfg, args.spec, not args.no_branch_check)
            print(json.dumps({k: state[k] for k in ("spec", "active", "halted", "agent_runs")}))
        return 0
    if command == "status":
        if args.json:
            print(json.dumps(run_state.load(root)))
        else:
            print(run_state.summary(root))
        return 0
    if command == "trust":
        print(f"trusted {cfg_mod.CONFIG_FILE} ({trust.trust_config(root)[:12]})")
        trust.record_guard(root, cfg.guard)
        print("gate config files re-baselined")
        return 0
    if command == "remote":
        print(json.dumps(telegram_status(), indent=2))
        return 0
    actions = {
        "start": lambda: run_state.start(cfg, args.spec, not args.no_branch_check),
        "agent": lambda: run_state.record_agent(cfg, args.role, args.fresh),
        "review": lambda: run_state.record_review(cfg, args.task, args.verdict),
        "done": lambda: run_state.complete(cfg, args.task, args.human),
        "assume": lambda: run_state.record_assumption(root, args.task, args.text),
        "halt": lambda: run_state.halt(root, run_state.require(root), args.reason),
        "resume": lambda: run_state.resume(root),
        "stop": lambda: run_state.stop(root),
    }
    state = actions[command]()
    print(json.dumps({k: state[k] for k in ("spec", "active", "halted", "agent_runs")}))
    return 0


def main(argv: list[str] | None = None) -> int:
    _utf8_output()
    args = _parser().parse_args(argv)
    if args.command in HOOKS:
        return _hook(args.command)
    try:
        if args.command == "init":
            root = _start_dir()
            for line in init_project(root, args.preset, args.specs_dir, args.force):
                print(line)
            write_shim(root, LAUNCHER)
            print(f"ready: run `{SDD} status`")
            return 0
        return _run_command(args, cfg_mod.load(_start_dir()))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
