"""The quality gate: the project's check commands plus a banned-wording scan.

Prints a short summary instead of full tool output, and a failure signature so the
orchestrator can spot the same failure coming back.
"""

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sdd_pilot.config import CheckStep, Config, Wording

MAX_DETAIL_LINES = 25
COVERAGE_LINE = re.compile(r"^(TOTAL\b|All files\b|Statements\s*:)")
_SKIP_DIRS = {".git", ".sdd", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}


@dataclass(frozen=True)
class StepResult:
    name: str
    ok: bool
    detail: tuple[str, ...]


def resolve_cmd(cmd: tuple[str, ...], root: Path) -> list[str]:
    """Find the executable the way a shell would (``npm`` is ``npm.cmd`` on Windows)."""
    exe = cmd[0]
    local = root / exe
    found = str(local) if local.exists() else shutil.which(exe)
    if found is None:
        raise FileNotFoundError(exe)
    return [found, *cmd[1:]]


def run_step(root: Path, step: CheckStep) -> StepResult:
    try:
        proc = subprocess.run(
            resolve_cmd(step.cmd, root),
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as error:
        return StepResult(step.name, False, (f"command not found: {error}",))
    lines = (proc.stdout + proc.stderr).splitlines()
    keep = re.compile(step.keep) if step.keep else None
    detail = [line for line in lines if keep and keep.search(line)][:MAX_DETAIL_LINES]
    if proc.returncode != 0 and not detail:
        detail = lines[-MAX_DETAIL_LINES:]
    detail += [line for line in lines if COVERAGE_LINE.search(line)][:1]
    return StepResult(step.name, proc.returncode == 0, tuple(detail))


def _negated(line: str, start: int, negations: tuple[str, ...]) -> bool:
    """True when one of the three words before the match is a negation."""
    before = re.findall(r"[A-Za-z']+", line[:start])[-3:]
    return any(word.lower() in negations for word in before)


def scan_wording(root: Path, wording: Wording) -> StepResult:
    if not wording.banned:
        return StepResult("wording", True, ())
    patterns = [re.compile(p, re.IGNORECASE) for p in wording.banned]
    hits = []
    for top in wording.scan:
        for path in sorted((root / top).rglob("*")):
            if path.suffix not in wording.suffixes or _SKIP_DIRS & set(path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for number, line in enumerate(text.splitlines(), start=1):
                if wording.allow_marker in line:
                    continue
                if any(
                    not _negated(line, match.start(), wording.negations)
                    for pattern in patterns
                    for match in pattern.finditer(line)
                ):
                    rel = path.relative_to(root).as_posix()
                    hits.append(f"{rel}:{number}: {line.strip()[:120]}")
    return StepResult("wording", not hits, tuple(hits[:MAX_DETAIL_LINES]))


def signature(results: list[StepResult]) -> str:
    """Hash of the failing lines with line numbers and timings removed."""
    parts = []
    for result in results:
        if result.ok:
            continue
        for line in result.detail:
            if COVERAGE_LINE.search(line):
                continue
            line = re.sub(r":\d+(?::\d+)?", ":", line)
            line = re.sub(r"\b\d+(?:\.\d+)?m?s\b", "", line)
            parts.append(f"{result.name}|{line}")
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()[:12] if parts else ""


def format_report(results: list[StepResult]) -> str:
    ok = all(r.ok for r in results)
    summary = ", ".join(f"{r.name} {'ok' if r.ok else 'FAIL'}" for r in results)
    out = [f"SDD CHECK: {'PASS' if ok else 'FAIL'} ({summary or 'no steps configured'})"]
    for result in results:
        coverage = [line for line in result.detail if COVERAGE_LINE.search(line)]
        out += [f"coverage: {' '.join(line.split())}" for line in coverage]
        if not result.ok:
            out.append(f"--- {result.name}")
            out += [line for line in result.detail if not COVERAGE_LINE.search(line)]
    if not ok:
        out.append(f"SIGNATURE: {signature(results)}")
    return "\n".join(out)


def run_all(cfg: Config) -> list[StepResult]:
    results = [run_step(cfg.root, step) for step in cfg.check]
    return [*results, scan_wording(cfg.root, cfg.wording)]
