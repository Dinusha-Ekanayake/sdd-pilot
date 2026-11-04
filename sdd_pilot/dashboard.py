"""Views of a run that cost no tokens: a one-line status and a static HTML dashboard.

Both are read-only. Approvals stay permission prompts; nothing here can approve,
resume or change a run, and the dashboard is a local file with no server behind it.
"""

import html
from pathlib import Path
from typing import Any

from sdd_pilot import usage
from sdd_pilot.safefs import ensure_safe
from sdd_pilot.tasks import DONE, HUMAN, Task, parse_tasks

DASHBOARD_FILE = Path(".sdd") / "dashboard.html"
REFRESH_SECONDS = 10
MAX_REASON = 48

State = dict[str, Any]


def _counts(tasks: list[Task]) -> tuple[int, int, int]:
    done = sum(t.status == DONE for t in tasks)
    waiting = sum(t.status == HUMAN for t in tasks)
    return done, waiting, len(tasks)


def _phase(state: State, tasks: list[Task]) -> str:
    if state.get("halted"):
        return "halted"
    if not state.get("active"):
        return "stopped"
    return "done" if not any(t.pending for t in tasks) else "running"


def status_line(state: State | None, tasks: list[Task]) -> str:
    """For Claude Code's status line, e.g. ``SDD 003 ▸ 4/9 ✓ · next T-003-05``."""
    if state is None:
        return ""
    done, waiting, total = _counts(tasks)
    parts = [f"SDD {state['spec']} ▸ {done}/{total} ✓"]
    totals = (state.get("usage") or {}).get("totals")
    if totals and usage.fresh(totals):
        parts.append(f"{usage.short(usage.fresh(totals))} tok")
    if waiting:
        parts.append(f"{waiting} awaiting you")
    phase = _phase(state, tasks)
    if phase == "halted":
        reason = str(state["halted"])
        parts.append(
            "halted: " + (reason[: MAX_REASON - 1] + "…" if len(reason) > MAX_REASON else reason)
        )
    elif phase == "running":
        parts.append("next " + next(t.id for t in tasks if t.pending))
    else:
        parts.append(phase)
    return " · ".join(parts)


_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--text:#1d1d1b;--muted:#6b6b66;--line:#e4e4df;
--ok:#1f7a4d;--warn:#a15c00;--bad:#b3261e;--accent:#2f5bd3}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--text:#ecece8;
--muted:#a3a39c;--line:#33332f;--ok:#5cc28f;--warn:#e0a24a;--bad:#f2867e;--accent:#8aa8ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:22px;margin:0 0 4px}.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:16px;margin:16px 0}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:13px}
.running{color:var(--accent)}.done{color:var(--ok)}.halted{color:var(--bad)}.stopped{color:var(--muted)}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin-top:12px}
.bar span{display:block;height:100%;background:var(--ok)}
.table{overflow-x:auto}table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
td.num{font-variant-numeric:tabular-nums}.risk-high{color:var(--warn);font-weight:600}
.risk-human{color:var(--accent);font-weight:600}code{font-size:13px}
"""


def _row(task: Task, entry: dict[str, Any]) -> str:
    status = {"[x]": "done", "[?]": "awaiting you", "[ ]": "open"}[task.status]
    cells = (
        f"<code>{html.escape(task.id)}</code>",
        html.escape(task.text),
        f'<span class="risk-{task.risk}">{task.risk}</span>',
        status,
        f'<span class="num">{entry.get("fix_attempts", 0)}</span>',
        f'<span class="num">{entry.get("review_rounds", 0)}</span>',
    )
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def render_dashboard(state: State, tasks: list[Task]) -> str:
    done, waiting, total = _counts(tasks)
    phase = _phase(state, tasks)
    entries: dict[str, Any] = state.get("tasks", {})
    rows = "\n".join(_row(t, entries.get(t.id, {})) for t in tasks)
    halted = (
        f'<div class="card"><strong class="halted">Halted:</strong> '
        f"{html.escape(str(state['halted']))}</div>"
        if state.get("halted")
        else ""
    )
    assumptions = [
        f"<li><code>{html.escape(task_id)}</code> {html.escape(str(text))}</li>"
        for task_id, entry in entries.items()
        for text in entry.get("assumptions", [])
    ]
    assumed = (
        f'<div class="card"><h2>Assumptions</h2><ul>{"".join(assumptions)}</ul></div>'
        if assumptions
        else ""
    )
    agents = max(int(state.get("agent_runs", 0)), int(state.get("observed_agent_runs", 0)))
    totals = (state.get("usage") or {}).get("totals")
    spent = f" · {html.escape(usage.describe(totals))}" if totals else ""
    percent = round(100 * (done + waiting) / total) if total else 0
    spec = html.escape(str(state["spec"]))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>SDD {spec} run</title><style>{_CSS}</style></head>
<body><main>
<h1>Spec {spec} <span class="pill {phase}">{phase}</span></h1>
<div class="muted">{html.escape(str(state.get("spec_dir", "")))} · {agents} agent runs{spent} ·
refreshes every {REFRESH_SECONDS}s · read-only</div>
<div class="card"><strong>{done}</strong> done · <strong>{waiting}</strong> awaiting your
sign-off · <strong>{total - done - waiting}</strong> open
<div class="bar"><span style="width:{percent}%"></span></div></div>
{halted}
<div class="card table"><table>
<thead><tr><th>ID</th><th>Task</th><th>Risk</th><th>Status</th><th>Fixes</th><th>Reviews</th></tr></thead>
<tbody>{rows}</tbody></table></div>
{assumed}
</main></body></html>
"""


def write_dashboard(root: Path, state: State) -> Path | None:
    """Regenerate ``.sdd/dashboard.html``; never fails the caller."""
    try:
        tasks = parse_tasks(root / str(state["spec_dir"]) / "tasks.md")
        path = root / DASHBOARD_FILE
        ensure_safe(root, path)
        path.write_text(render_dashboard(state, tasks), encoding="utf-8")
    except (OSError, ValueError, KeyError):
        return None
    return path
