"""CLI: ``sdd <command>``. In a project, Claude runs it as ``bash .sdd/bin/sdd <command>``."""

import argparse
import io
import json
import os
import sys
from pathlib import Path

from specsteward import config as cfg_mod
from specsteward import graph, prereqs, trust
from specsteward import state as run_state
from specsteward.analyze import analyze
from specsteward.analyze import format_findings as format_analysis
from specsteward.brief import write_brief
from specsteward.check import format_report, run_all, signature
from specsteward.dashboard import status_line, write_dashboard
from specsteward.doctor import format_findings, run_doctor
from specsteward.hooks import (
    SDD,
    format_file,
    guard_decision,
    session_context,
    stop_decision,
    write_shim,
)
from specsteward.init import enable_statusline, init_project
from specsteward.presets import PRESETS
from specsteward.remote import telegram_status
from specsteward.tasks import parse_tasks

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = PLUGIN_ROOT / "bin" / "sdd"
ENTRY = PLUGIN_ROOT / "bin" / "sdd_entry.py"
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
    init.add_argument("--preset", choices=PRESETS, default="auto")
    init.add_argument("--specs-dir", default="specs")
    init.add_argument("--force", action="store_true")
    init.add_argument("--statusline", action="store_true", help="show the run in the status line")
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
    approve.add_argument("--anyway", action="store_true", help="approve despite CRITICAL findings")
    worktree = sub.add_parser("worktree", help="a parallel git worktree for one spec")
    worktree.add_argument("spec")
    sub.add_parser("converge", help="count a converge pass and print the next task id")
    analyze_cmd = sub.add_parser("analyze", help="check a spec, plan and tasks before approval")
    analyze_cmd.add_argument("spec")
    agent = sub.add_parser("agent", help="count a subagent run")
    agent.add_argument("role", choices=("planner", "implementer", "reviewer", "converger", "clerk"))
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
    graph_cmd = sub.add_parser("graph", help="code graph: show its status, or sync it now")
    graph_cmd.add_argument("action", choices=("status", "sync"))
    sub.add_parser("statusline", help="one line for Claude Code's status line")
    sub.add_parser("dashboard", help="write .sdd/dashboard.html and print its path")
    install = sub.add_parser("install", help="install a prerequisite (bun, for phone control)")
    install.add_argument("tool", choices=("bun",))
    doctor = sub.add_parser("doctor", help="check the setup and say how to fix problems")
    doctor.add_argument("--json", action="store_true")
    for name in ("next", "resume", "stop", "remote", *HOOKS):
        sub.add_parser(name)
    return parser


def _utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):  # Windows consoles default to cp1252
            stream.reconfigure(encoding="utf-8", errors="replace")


def _hook(command: str) -> int:
    """Hooks never fail the session: outside an sdd project they do nothing, and an error
    inside one is reported on stderr instead of breaking the user's turn."""
    try:
        cfg = cfg_mod.load(_start_dir())
    except (ValueError, OSError):
        return 0
    try:
        _dispatch_hook(command, cfg)
    except Exception as error:  # noqa: BLE001 - a hook must never take the session down
        print(f"specsteward {command}: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


def _payload() -> dict[str, object]:
    """The hook's JSON input, or {} when there is none (a terminal, or a test)."""
    try:
        if sys.stdin.isatty():
            return {}
        data = json.load(sys.stdin)
    except (OSError, ValueError, AttributeError):
        return {}
    return data if isinstance(data, dict) else {}


def _dispatch_hook(command: str, cfg: cfg_mod.Config) -> None:
    if command in ("hook-stop", "hook-subagent-stop"):
        run_state.observe_usage(cfg, _payload().get("transcript_path"))
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
        text = session_context()
        # Only for a trusted sdd.toml: it chooses the graphify version that gets installed.
        if cfg.graphify_auto and trust.config_trusted(cfg.root):
            graph.ensure_ignores(cfg.root)  # now, not mid-run from the background sync
            graph.start_background_sync(cfg.root, ENTRY)
            text += graph.session_hint(cfg.root)
        prereqs.start_background_bun_install(ENTRY)  # only if phone control is set up
        context = {"hookEventName": "SessionStart", "additionalContext": text}
        print(json.dumps({"hookSpecificOutput": context}))


def _graph(cfg: cfg_mod.Config, action: str) -> int:
    if action == "status":
        found = graph.find_graphify()
        print(json.dumps({"graphify": found, "graph": graph.graph_status(cfg.root)}))
        return 0
    try:
        if not trust.config_trusted(cfg.root):
            raise ValueError("sdd.toml is not trusted; review it, then run `sdd trust`")
        lines = graph.sync(cfg.root, cfg.graphify_version)
    finally:
        graph.release_lock(cfg.root)
    print("\n".join(lines))
    return 1 if any(line.startswith(("could not", "`graphify")) for line in lines) else 0


def _statusline() -> int:
    """Never fails and prints nothing outside a run, so it is safe in any status line."""
    start = _start_dir()
    if not sys.stdin.isatty():
        try:
            payload = json.load(sys.stdin)
            start = Path(payload.get("workspace", {}).get("project_dir") or start)
        except (ValueError, AttributeError, OSError):
            pass
    try:
        root = cfg_mod.find_root(start)
        state = run_state.load(root)
        tasks = parse_tasks(run_state.tasks_path(root, state)) if state else []
        print(status_line(state, tasks))
    except Exception:  # noqa: BLE001 - a status line must never show a traceback
        pass
    return 0


def _doctor(as_json: bool) -> int:
    found = run_doctor(_start_dir())
    if as_json:
        print(json.dumps([vars(item) for item in found], indent=2))
    else:
        print(format_findings(found))
    return 1 if any(item.level == "FAIL" for item in found) else 0


def _check(cfg: cfg_mod.Config, task: str | None) -> int:
    before = run_state.run_tree(cfg)  # the gate runs project code; see record_pass
    results = run_all(cfg)
    print(format_report(results))
    if all(r.ok for r in results):
        run_state.record_pass(cfg, before)
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
    if command == "worktree":
        target = run_state.create_worktree(cfg, args.spec)
        write_shim(target, LAUNCHER)
        print(f"worktree ready: {target.as_posix()}")
        print(f"open Claude Code there and run /specsteward:run {args.spec}")
        return 0
    if command == "converge":
        print(json.dumps(run_state.converge_round(cfg)))
        return 0
    if command == "next":
        print(json.dumps(run_state.next_step(cfg)))
        return 0
    if command == "brief":
        spec_dir = root / run_state.require(root)["spec_dir"]
        print(write_brief(cfg, spec_dir, args.tasks, SDD).relative_to(root).as_posix())
        return 0
    if command == "analyze":
        spec_dir = cfg.spec_dir(args.spec)
        found = analyze(spec_dir)
        print(format_analysis(spec_dir, found))
        return 1 if any(f.level == "CRITICAL" for f in found) else 0
    if command == "approve":
        found = analyze(cfg.spec_dir(args.spec))
        if any(f.level == "CRITICAL" for f in found) and not args.anyway:
            print(format_analysis(cfg.spec_dir(args.spec), found))
            raise ValueError("resolve the CRITICAL findings first (or pass --anyway)")
        print(f"spec {args.spec}: {run_state.approve(cfg, args.spec, args.via)}")
        if args.start:  # one permission prompt for "approve and go", e.g. from a phone
            current = run_state.load(root)
            if current and current["active"] and current["spec"] == args.spec:
                state = run_state.resume(root)  # tasks were added mid-run, e.g. by converge
            else:
                state = run_state.start(cfg, args.spec, not args.no_branch_check)
            print(json.dumps({k: state[k] for k in ("spec", "active", "halted", "agent_runs")}))
        return 0
    if command == "status":
        if args.json:
            print(json.dumps(run_state.load(root)))
        else:
            print(run_state.summary(root))
        return 0
    if command == "graph":
        return _graph(cfg, args.action)
    if command == "dashboard":
        state = run_state.require(root)
        path = write_dashboard(root, state)
        print(path.as_posix() if path else "could not write the dashboard")
        return 0 if path else 1
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
        if args.command == "statusline":
            return _statusline()
        if args.command == "install":
            ok, message = prereqs.install_bun()
            print(message)
            return 0 if ok else 1
        if args.command == "doctor":
            return _doctor(args.json)
        if args.command == "init":
            root = _start_dir()
            for line in init_project(root, args.preset, args.specs_dir, args.force):
                print(line)
            if args.statusline:
                print(enable_statusline(root))
            cfg = cfg_mod.load(root)
            trusted = trust.config_trusted(root)
            if cfg.graphify_auto and trusted and graph.start_background_sync(root, ENTRY):
                print(f"building the code graph in the background ({graph.LOG_FILE.as_posix()})")
            write_shim(root, LAUNCHER)
            print(f"ready: run `{SDD} status`")
            return 0
        return _run_command(args, cfg_mod.load(_start_dir()))
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
