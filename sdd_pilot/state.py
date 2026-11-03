"""Run state in ``.sdd/state.json``: progress, caps, halts and the approval log."""

import json
import re
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sdd_pilot import trust
from sdd_pilot.config import Config
from sdd_pilot.tasks import DONE, HUMAN, next_group, parse_tasks, set_status

STATE_DIR = Path(".sdd")
STATE_FILE = STATE_DIR / "state.json"
APPROVALS_FILE = STATE_DIR / "approvals.log"

State = dict[str, Any]


def load(root: Path) -> State | None:
    path = root / STATE_FILE
    if not path.exists():
        return None
    state: State = json.loads(path.read_text(encoding="utf-8"))
    return state


def save(root: Path, state: State) -> None:
    path = root / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
    stamp = f"{cfg.approved_word} ({date.today().isoformat()})"
    new_text = re.sub(cfg.status_regex, lambda m: f"{m.group(1)}{stamp}", text, count=1)
    path.write_text(new_text, encoding="utf-8")
    digest = trust.file_hash(path) or ""
    trust.record_approval(cfg.root, spec, digest)
    entry = {
        "time": datetime.now(UTC).isoformat(timespec="seconds"),
        "spec": spec,
        "sha256": digest,
        "via": via,  # reported by the caller; the permission prompt is the real gate
    }
    log = cfg.root / APPROVALS_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return stamp


def approval_problem(cfg: Config, spec: str, directory: Path) -> str | None:
    """Why the spec does not count as approved right now, or None when it does."""
    spec_file = directory / "spec.md"
    name = f"{directory.name}/spec.md"
    if not cfg.is_approved(spec_file.read_text(encoding="utf-8")):
        return f"{name} is not approved; get user approval first"
    recorded = trust.approved_hash(cfg.root, spec)
    if recorded is None:
        return f"{name} says approved but has no recorded approval; run `sdd approve {spec}`"
    if recorded != trust.file_hash(spec_file):
        return f"{name} changed after it was approved; the user must approve it again"
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
    parse_tasks(directory / "tasks.md")  # fail early on a malformed table
    trust.record_guard(cfg.root, cfg.guard)  # baseline for the gate config check
    state: State = {
        "spec": spec,
        "spec_dir": directory.relative_to(cfg.root).as_posix(),
        "active": True,
        "halted": None,
        "agent_runs": 0,
        "implementer_tasks": 0,
        "last_block_done": -1,
        "tasks": {},
    }
    save(cfg.root, state)
    return state


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
    problem = approval_problem(cfg, state["spec"], cfg.root / state["spec_dir"])
    if problem:
        halt(cfg.root, state, problem)
        return {"status": "halted", "reason": problem}
    tasks = parse_tasks(tasks_path(cfg.root, state))
    group = next_group(tasks, cfg.max_group, cfg.max_group_high)
    if not group:
        return {"status": "done", "spec": state["spec"]}
    risk = group[0].risk
    return {
        "status": "run",
        "tasks": [t.id for t in group],
        "risk": risk,
        "reviewer_model": cfg.models[risk],
        "human_signoff": risk == "human",
        "restart_implementer": state["implementer_tasks"] >= cfg.limits.restart_after_tasks,
    }


def record_agent(cfg: Config, role: str, fresh: bool) -> State:
    state = require(cfg.root)
    state["agent_runs"] += 1
    if role == "implementer" and fresh:
        state["implementer_tasks"] = 0
    if state["agent_runs"] > cfg.limits.max_agent_runs:
        return halt(cfg.root, state, f"agent run cap reached ({cfg.limits.max_agent_runs})")
    save(cfg.root, state)
    return state


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
    entry = _task(state, task_id)
    entry["review_rounds"] += 1
    if verdict == "changes" and entry["review_rounds"] >= cfg.limits.max_review_rounds:
        return halt(cfg.root, state, f"{task_id}: review round cap reached with open findings")
    save(cfg.root, state)
    return state


def record_assumption(root: Path, task_id: str, text: str) -> State:
    state = require(root)
    _task(state, task_id)["assumptions"].append(text)
    save(root, state)
    return state


def complete(root: Path, task_id: str, human: bool) -> State:
    state = require(root)
    set_status(tasks_path(root, state), task_id, HUMAN if human else DONE)
    state["implementer_tasks"] += 1
    save(root, state)
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
