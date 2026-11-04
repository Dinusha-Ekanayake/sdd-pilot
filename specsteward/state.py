"""Run state in ``.sdd/state.json``: progress, caps, halts and the approval log."""

import hashlib
import json
import os
import re
import secrets
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from specsteward import trust, usage
from specsteward.config import SPEC_NUMBER, Config
from specsteward.dashboard import write_dashboard
from specsteward.graph import ensure_ignores
from specsteward.safefs import ensure_safe
from specsteward.tasks import DONE, HUMAN, TODO, next_group, parse_tasks, set_status
from specsteward.worktree import fingerprint

STATE_DIR = Path(".sdd")
STATE_FILE = STATE_DIR / "state.json"
APPROVALS_FILE = STATE_DIR / "approvals.log"

State = dict[str, Any]


def load(root: Path) -> State | None:
    """The run started by ``sdd start`` here, or None.

    State a repository ships (a committed ``.sdd/state.json``) does not count: its run id
    must match the one ``start`` recorded in the trust store, and its fields must be sane,
    because they end up in prompts (the Stop hook's continue reason).
    """
    path = root / STATE_FILE
    if not path.exists():
        return None
    state: State = json.loads(path.read_text(encoding="utf-8"))
    run_id = state.get("run_id")
    if not run_id or run_id != trust.current_run(root):
        return None
    spec_dir = str(state.get("spec_dir", ""))
    if not SPEC_NUMBER.fullmatch(str(state.get("spec", ""))) or ".." in Path(spec_dir).parts:
        return None
    return state


def save(root: Path, state: State) -> None:
    path = root / STATE_FILE
    ensure_safe(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")  # write then rename, so a crash never leaves half a file
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    write_dashboard(root, state)  # the read-only HTML view stays current


def require(root: Path) -> State:
    state = load(root)
    if state is None or not state["active"]:
        raise ValueError("no active SDD run; start one with `sdd start <NNN>`")
    return state


def tasks_path(root: Path, state: State) -> Path:
    return root / str(state["spec_dir"]) / "tasks.md"


def current_branch(root: Path) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError("not a git repository")
    return proc.stdout.strip()


def approve(cfg: Config, spec: str, via: str) -> str:
    """Mark a spec approved, bind the approval to its content, and log it.

    Projects should put ``sdd approve`` behind an ``ask`` permission rule, so the
    approval is a permission prompt only the human can answer (in the terminal, or
    relayed to their phone by a channel plugin). The sha256 of the approved ``spec.md``
    goes to the trust store outside the repository, so editing the status line by hand,
    or changing the spec after approval, does not count as approval.
    """
    path = cfg.spec_dir(spec) / "spec.md"
    text = path.read_text(encoding="utf-8")
    if not re.search(cfg.status_regex, text):
        raise ValueError(f"{path.name} has no status line matching {cfg.status_regex!r}")
    added = _appended_tasks(cfg, spec, path.parent)  # checks before anything is written
    stamp = f"{cfg.approved_word} ({date.today().isoformat()})"
    new_text = re.sub(cfg.status_regex, lambda m: f"{m.group(1)}{stamp}", text, count=1)
    ensure_safe(cfg.root, path)
    path.write_text(new_text, encoding="utf-8")
    digest = approval_digest(path.parent)
    trust.record_approval(cfg.root, spec, digest)
    if added is not None:
        trust.record_ticks(cfg.root, spec, added)
    entry = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "spec": spec,
        "sha256": digest,
        "via": via,  # reported by the caller; the permission prompt is the real gate
    }
    log = cfg.root / APPROVALS_FILE
    ensure_safe(cfg.root, log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return stamp


def _appended_tasks(cfg: Config, spec: str, directory: Path) -> dict[str, str] | None:
    """For a spec with a run in progress: the ticks after approving tasks appended to it
    (for example by converge). Existing rows must be unchanged and new rows open.
    None when no run of this spec is in progress."""
    state = load(cfg.root)
    recorded = trust.recorded_ticks(cfg.root, spec)
    if state is None or not state["active"] or state["spec"] != spec or recorded is None:
        return None
    actual = {t.id: t.status for t in parse_tasks(directory / "tasks.md")}
    changed = sorted(i for i in recorded if actual.get(i) != recorded[i])
    if changed:
        raise ValueError(
            f"existing tasks changed during the run ({', '.join(changed)}); restore them first"
        )
    new = {i: s for i, s in actual.items() if i not in recorded}
    if any(status != TODO for status in new.values()):
        raise ValueError("tasks added during a run must be open ([ ])")
    return {**recorded, **new}


def converge_round(cfg: Config) -> dict[str, Any]:
    """Count a converge pass once every task is ticked; give the next free task id."""
    state = require(cfg.root)
    tasks = parse_tasks(tasks_path(cfg.root, state))
    if any(t.pending for t in tasks):
        raise ValueError("converge runs after every task is ticked; run `sdd next`")
    state["converge_rounds"] = int(state.get("converge_rounds", 0)) + 1
    limit = cfg.limits.max_converge_rounds
    if state["converge_rounds"] > limit:
        halt(cfg.root, state, f"converge round cap reached ({limit}); ship or plan a new spec")
        return {"status": "halted", "reason": state["halted"]}
    save(cfg.root, state)
    last = max(int(t.id.rsplit("-", 1)[1]) for t in tasks)
    return {
        "status": "converge",
        "round": state["converge_rounds"],
        "next_id": f"T-{state['spec']}-{last + 1:02d}",
    }


def approval_digest(directory: Path) -> str:
    """What the user approves: spec.md, plan.md and the task definitions.

    Task statuses are left out, so ticking does not void the approval; ticks are checked
    separately (see ``tick_problem``).
    """
    digest = hashlib.sha256()
    for name in ("spec.md", "plan.md"):
        path = directory / name
        digest.update(name.encode() + b"\0" + (path.read_bytes() if path.is_file() else b""))
    try:
        rows = parse_tasks(directory / "tasks.md")
    except (OSError, ValueError):
        rows = []
    for task in rows:
        digest.update("\0".join(("task", task.id, task.text, task.test, task.risk)).encode())
    return digest.hexdigest()


def tick_problem(cfg: Config, state: State) -> str | None:
    """Task statuses that changed outside ``sdd done`` (a hand-ticked or deleted row)."""
    recorded = trust.recorded_ticks(cfg.root, state["spec"])
    if recorded is None:
        return "no recorded task statuses for this run; start it with `sdd start`"
    actual = {t.id: t.status for t in parse_tasks(tasks_path(cfg.root, state))}
    changed = sorted(i for i in recorded.keys() | actual.keys() if recorded.get(i) != actual.get(i))
    if changed:
        return f"tasks.md changed outside `sdd done` ({', '.join(changed)}); restore it"
    return None


def integrity_problem(cfg: Config, state: State) -> str | None:
    """Approval and ticks, checked before anything trusts the spec or the task table."""
    directory = cfg.root / state["spec_dir"]
    return approval_problem(cfg, state["spec"], directory) or tick_problem(cfg, state)


def approval_problem(cfg: Config, spec: str, directory: Path) -> str | None:
    """Why the spec does not count as approved right now, or None when it does."""
    spec_file = directory / "spec.md"
    name = f"{directory.name}/spec.md"
    if not cfg.is_approved(spec_file.read_text(encoding="utf-8")):
        return f"{name} is not approved; get user approval first"
    recorded = trust.approved_hash(cfg.root, spec)
    if recorded is None:
        return f"{name} says approved but has no recorded approval; run `sdd approve {spec}`"
    if recorded != approval_digest(directory):
        return (
            f"{directory.name} (spec, plan or task table) changed after it was approved; "
            "the user must approve it again"
        )
    return None


def start(cfg: Config, spec: str, check_branch: bool = True) -> State:
    """Start a fresh run. Refuses while a run is active, so counters are never wiped by accident."""
    current = load(cfg.root)
    if current is not None and current["active"]:
        hint = "use `sdd resume`" if current["spec"] == spec else "run `sdd stop` first"
        raise ValueError(f"a run for spec {current['spec']} is already active; {hint}")
    directory = cfg.spec_dir(spec)
    problem = approval_problem(cfg, spec, directory)
    if problem:
        raise ValueError(problem)
    prefix = cfg.branch_prefix.format(spec=spec)
    if check_branch and prefix and not current_branch(cfg.root).startswith(prefix):
        raise ValueError(f"switch to a {prefix}* branch before starting the run")
    tasks = parse_tasks(directory / "tasks.md")  # fail early on a malformed table
    trust.record_ticks(cfg.root, spec, {t.id: t.status for t in tasks})
    trust.record_guard(cfg.root, cfg.guard)  # baseline for the gate config check
    if cfg.graphify_auto:
        ensure_ignores(cfg.root)  # so a background graph sync cannot change the tree mid-run
    run_id = secrets.token_hex(8)
    trust.record_run(cfg.root, run_id)
    state: State = {
        "run_id": run_id,
        "spec": spec,
        "spec_dir": directory.relative_to(cfg.root).as_posix(),
        "active": True,
        "halted": None,
        "agent_runs": 0,
        "implementer_tasks": 0,
        "last_block_done": -1,
        "observed_agent_runs": 0,
        "started_at": datetime.now(UTC).isoformat(),
        "usage": usage.empty(),
        "gate": _fresh_gate([]),
        "tasks": {},
    }
    save(cfg.root, state)
    return state


def _fresh_gate(group: list[str]) -> dict[str, Any]:
    """Which group is in flight, and the tree fingerprints its gate and review last saw."""
    return {"group": group, "passed": None, "reviewed": None}


def tree(root: Path, state: State) -> str:
    """Fingerprint of the working tree, leaving out the task table that ``done`` ticks."""
    return fingerprint(root, exclude=(f"{state['spec_dir']}/tasks.md",))


def _gate(state: State) -> dict[str, Any]:
    gate: dict[str, Any] = state.setdefault("gate", _fresh_gate([]))
    return gate


def _task(state: State, task_id: str) -> dict[str, Any]:
    entry: dict[str, Any] = state["tasks"].setdefault(
        task_id, {"failures": [], "fix_attempts": 0, "review_rounds": 0, "assumptions": []}
    )
    return entry


def halt(root: Path, state: State, reason: str) -> State:
    state["halted"] = reason
    save(root, state)
    return state


def next_step(cfg: Config) -> dict[str, Any]:
    state = require(cfg.root)
    if state["halted"]:
        return {"status": "halted", "reason": state["halted"]}
    problem = integrity_problem(cfg, state)
    if problem:
        halt(cfg.root, state, problem)
        return {"status": "halted", "reason": problem}
    tasks = parse_tasks(tasks_path(cfg.root, state))
    gate = _gate(state)
    # A group stays in flight, with its gate and review results, until all of it is ticked.
    remaining = [t for t in tasks if t.pending and t.id in gate["group"]]
    group = remaining or next_group(tasks, cfg.max_group, cfg.max_group_high)
    if not group:
        return {"status": "done", "spec": state["spec"]}
    risk = group[0].risk
    ids = [t.id for t in group]
    if not remaining:
        state["gate"] = _fresh_gate(ids)
        save(cfg.root, state)
    return {
        "status": "run",
        "tasks": ids,
        "risk": risk,
        "review": risk not in cfg.review_skip,
        "reviewer_model": None if risk in cfg.review_skip else cfg.models[risk],
        "human_signoff": risk == "human",
        "restart_implementer": state["implementer_tasks"] >= cfg.limits.restart_after_tasks,
    }


def agent_count(state: State) -> int:
    """Declared (``sdd agent``) or observed (SubagentStop hook) runs, whichever is higher."""
    return max(int(state["agent_runs"]), int(state.get("observed_agent_runs", 0)))


def _cap_agents(cfg: Config, state: State) -> State:
    if agent_count(state) > cfg.limits.max_agent_runs:
        return halt(cfg.root, state, f"agent run cap reached ({cfg.limits.max_agent_runs})")
    save(cfg.root, state)
    return state


def record_agent(cfg: Config, role: str, fresh: bool) -> State:
    state = require(cfg.root)
    state["agent_runs"] += 1
    if role == "implementer" and fresh:
        state["implementer_tasks"] = 0
    return _cap_agents(cfg, state)


def observe_agent(cfg: Config) -> State | None:
    """Count a finished subagent from the SubagentStop hook, so the cap is not honour-based."""
    state = load(cfg.root)
    if state is None or not state["active"] or state["halted"]:
        return None
    state["observed_agent_runs"] = int(state.get("observed_agent_runs", 0)) + 1
    return _cap_agents(cfg, state)


def run_tree(cfg: Config) -> str | None:
    """The fingerprint the gate starts from, or None outside a run."""
    state = load(cfg.root)
    if state is None or not state["active"]:
        return None
    return tree(cfg.root, state)


def observe_usage(cfg: Config, transcript_path: object) -> State | None:
    """Add the run's new token usage from the transcripts; halt over ``max_tokens``."""
    state = load(cfg.root)
    if state is None or not state["active"] or state["halted"] or not transcript_path:
        return None
    since = datetime.fromisoformat(str(state.get("started_at") or datetime.now(UTC).isoformat()))
    state["usage"] = usage.collect(state.get("usage") or usage.empty(), str(transcript_path), since)
    spent = usage.fresh(state["usage"]["totals"])
    budget = cfg.limits.max_tokens
    if budget and spent > budget:
        return halt(
            cfg.root, state, f"token budget reached ({usage.short(spent)} of {usage.short(budget)})"
        )
    save(cfg.root, state)
    return state


def record_pass(cfg: Config, before: str | None = None) -> State | None:
    """Remember the tree a passing gate saw (only during a run, for the group in flight).

    With ``before`` (the fingerprint taken as the gate started), a tree that changed while
    the gate ran is not recorded: the pass would not describe the code as it is now.
    """
    state = load(cfg.root)
    if state is None or not state["active"] or not _gate(state)["group"]:
        return None
    now = tree(cfg.root, state)
    if before is not None and before != now:
        raise ValueError("files changed while the gate ran; run `sdd check` again")
    _gate(state)["passed"] = now
    save(cfg.root, state)
    return state


def current_task(cfg: Config) -> str | None:
    """First task of the group in flight, which failures are recorded against."""
    state = load(cfg.root)
    if state is None or not state["active"]:
        return None
    group = _gate(state)["group"]
    return str(group[0]) if group else None


def record_failure(cfg: Config, task_id: str, signature: str) -> State:
    state = require(cfg.root)
    entry = _task(state, task_id)
    if signature in entry["failures"]:
        return halt(cfg.root, state, f"{task_id}: same check failure twice ({signature})")
    entry["failures"].append(signature)
    entry["fix_attempts"] += 1
    if entry["fix_attempts"] > cfg.limits.max_fix_attempts:
        return halt(cfg.root, state, f"{task_id}: fix attempt cap reached")
    save(cfg.root, state)
    return state


def record_review(cfg: Config, task_id: str, verdict: str) -> State:
    if verdict not in ("clean", "changes"):
        raise ValueError("verdict must be 'clean' or 'changes'")
    state = require(cfg.root)
    group = _gate(state)["group"]
    if group and task_id not in group:
        raise ValueError(f"{task_id} is not in the group in flight ({group}); review that group")
    entry = _task(state, task_id)
    entry["review_rounds"] += 1
    _gate(state)["reviewed"] = tree(cfg.root, state) if verdict == "clean" else None
    if verdict == "changes" and entry["review_rounds"] >= cfg.limits.max_review_rounds:
        return halt(cfg.root, state, f"{task_id}: review round cap reached with open findings")
    save(cfg.root, state)
    return state


def record_assumption(root: Path, task_id: str, text: str) -> State:
    state = require(root)
    _task(state, task_id)["assumptions"].append(text)
    save(root, state)
    return state


def done_problem(cfg: Config, state: State, task_id: str, risk: str = "high") -> str | None:
    """Why ``task_id`` cannot be ticked yet, or None when it can."""
    gate = _gate(state)
    if task_id not in gate["group"]:
        return f"{task_id} is not in the group in flight ({gate['group']}); run `sdd next`"
    now = tree(cfg.root, state)
    if gate["passed"] != now:
        return "no passing `sdd check` for the code as it is now; run the gate again"
    if risk not in cfg.review_skip and gate["reviewed"] != now:
        return "no clean review for the code as it is now; review it (again) first"
    return None


def complete(cfg: Config, task_id: str, human: bool = False) -> State:
    """Tick a task, but only after a passing gate and a clean review of the current tree."""
    state = require(cfg.root)
    path = tasks_path(cfg.root, state)
    problem = integrity_problem(cfg, state)
    if problem:
        halt(cfg.root, state, problem)
        raise ValueError(problem)
    risk = {t.id: t.risk for t in parse_tasks(path)}.get(task_id, "high")
    problem = done_problem(cfg, state, task_id, risk)
    if problem:
        raise ValueError(problem)
    status = HUMAN if human or risk == "human" else DONE
    ensure_safe(cfg.root, path)
    set_status(path, task_id, status)
    ticks = trust.recorded_ticks(cfg.root, state["spec"]) or {}
    trust.record_ticks(cfg.root, state["spec"], {**ticks, task_id: status})
    state["implementer_tasks"] += 1
    save(cfg.root, state)
    return state


def resume(root: Path) -> State:
    """Clear a halt after the user has dealt with it; open tasks get fresh counters."""
    state = require(root)
    state["halted"] = None
    state["last_block_done"] = -1
    open_ids = {t.id for t in parse_tasks(tasks_path(root, state)) if t.pending}
    for task_id in open_ids & set(state["tasks"]):
        state["tasks"][task_id].update(failures=[], fix_attempts=0, review_rounds=0)
    save(root, state)
    return state


def stop(root: Path) -> State:
    state = require(root)
    state["active"] = False
    save(root, state)
    return state


def summary(root: Path) -> str:
    """A few plain lines for a phone screen: progress, halt reason, assumptions."""
    state = load(root)
    if state is None:
        return "No SDD run in this project."
    tasks = parse_tasks(tasks_path(root, state))
    done = [t.id for t in tasks if t.status == DONE]
    waiting = [t.id for t in tasks if t.status == HUMAN]
    open_ids = [t.id for t in tasks if t.pending]
    lines = [
        f"Spec {state['spec']}: {len(done)} done, {len(waiting)} waiting for you, "
        f"{len(open_ids)} open. {'Running' if state['active'] else 'Stopped'}.",
    ]
    if state["halted"]:
        lines.append(f"Halted: {state['halted']}")
    if waiting:
        lines.append(f"Sign-off needed: {', '.join(waiting)}")
    if state.get("usage"):
        lines.append(f"Used: {usage.describe(state['usage']['totals'])}")
    if open_ids:
        lines.append(f"Next: {open_ids[0]}")
    assumptions = [
        f"{task_id}: {text}"
        for task_id, entry in state["tasks"].items()
        for text in entry.get("assumptions", [])
    ]
    if assumptions:
        lines.append("Assumptions:\n- " + "\n- ".join(assumptions[-5:]))
    return "\n".join(lines)
