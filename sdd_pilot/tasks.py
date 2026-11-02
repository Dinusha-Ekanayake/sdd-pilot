"""Parse and update the task table in ``<specs_dir>/<NNN>-<slug>/tasks.md``.

The table needs the columns ID, Task, Test and Status; Risk is optional (default ``low``).
Status is ``[ ]`` open, ``[x]`` done or ``[?]`` prepared and waiting for human sign-off.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from sdd_pilot.config import RISKS

TODO, DONE, HUMAN = "[ ]", "[x]", "[?]"
STATUSES = (TODO, DONE, HUMAN)

_ROW = re.compile(r"^\|\s*(T-\d{3}-\d{2})\s*\|")
_STATUS_CELL = re.compile(r"\[[ x?]\]\s*\|\s*$")


@dataclass(frozen=True)
class Task:
    id: str
    text: str
    test: str
    risk: str
    status: str

    @property
    def pending(self) -> bool:
        return self.status == TODO


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_tasks(path: Path) -> list[Task]:
    header: list[str] = []
    tasks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("| ID"):
            header = [cell.lower() for cell in _cells(line)]
            continue
        if not _ROW.match(line):
            continue
        row = dict(zip(header, _cells(line), strict=False))
        risk = row.get("risk", "low") or "low"
        if risk not in RISKS:
            raise ValueError(f"{row['id']}: risk must be one of {RISKS}, got {risk!r}")
        status = row.get("status", "")
        if status not in STATUSES:
            raise ValueError(f"{row['id']}: status must be one of {STATUSES}, got {status!r}")
        tasks.append(Task(row["id"], row.get("task", ""), row.get("test", ""), risk, status))
    if not tasks:
        raise ValueError(f"no tasks found in {path}")
    return tasks


def set_status(path: Path, task_id: str, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status {status!r}")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for i, line in enumerate(lines):
        match = _ROW.match(line)
        if match and match.group(1) == task_id:
            ending = "\n" if line.endswith("\n") else ""
            lines[i] = _STATUS_CELL.sub(f"{status} |", line.rstrip("\n")) + ending
            path.write_text("".join(lines), encoding="utf-8")
            return
    raise ValueError(f"task {task_id} not found in {path}")


def next_group(tasks: list[Task], max_size: int = 3, max_high: int = 2) -> list[Task]:
    """Consecutive pending tasks of the same risk. ``human`` tasks always run alone."""
    pending = [t for t in tasks if t.pending]
    if not pending:
        return []
    first = pending[0]
    if first.risk == "human":
        return [first]
    limit = max_high if first.risk == "high" else max_size
    group = [first]
    for task in tasks[tasks.index(first) + 1 :]:
        if len(group) >= limit or not task.pending or task.risk != first.risk:
            break
        group.append(task)
    return group
