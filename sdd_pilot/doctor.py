"""``sdd doctor``: check everything a run depends on, and say how to fix what is missing."""

import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sdd_pilot import config as cfg_mod
from sdd_pilot import graph, prereqs, trust
from sdd_pilot.check import resolve_cmd
from sdd_pilot.hooks import SHIM
from sdd_pilot.init import ASK, DENY
from sdd_pilot.remote import telegram_status

OK, WARN, FAIL = "ok", "warn", "FAIL"
MIN_PYTHON = (3, 11)


@dataclass(frozen=True)
class Finding:
    level: str
    what: str
    fix: str = ""


def _python() -> Finding:
    version = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] >= MIN_PYTHON:
        return Finding(OK, f"Python {version}")
    return Finding(FAIL, f"Python {version} is too old", "install Python 3.11+ or set SDD_PYTHON")


def _git(root: Path) -> Finding:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return Finding(WARN, "git not found", "install git; branch checks and diffs need it")
    if proc.returncode != 0:
        return Finding(WARN, "not a git repository", "run `git init`; reviews read `git diff`")
    return Finding(OK, f"git branch {proc.stdout.strip()}")


def _checks(cfg: cfg_mod.Config) -> list[Finding]:
    if not trust.config_trusted(cfg.root):
        return [Finding(FAIL, "sdd.toml is not trusted", "review sdd.toml, then `sdd trust`")]
    found = [Finding(OK, "sdd.toml is trusted")]
    if not cfg.check:
        found.append(Finding(WARN, "no [[check]] steps", "add lint, type and test commands"))
    for step in cfg.check:
        try:
            exe = Path(resolve_cmd(step.cmd, cfg.root)[0]).name
        except FileNotFoundError as error:
            found.append(
                Finding(FAIL, f"check {step.name!r}: {error} not found", "install it or fix cmd")
            )
        else:
            found.append(Finding(OK, f"check {step.name!r} runs {exe}"))
    return found


def _settings(root: Path) -> list[dict[str, Any]]:
    files = (
        root / ".claude" / "settings.json",
        root / ".claude" / "settings.local.json",
        Path.home() / ".claude" / "settings.json",
    )
    out = []
    for path in files:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _permissions(root: Path) -> list[Finding]:
    settings = _settings(root)
    rules = {
        key: {rule for s in settings for rule in s.get("permissions", {}).get(key, [])}
        for key in ("ask", "deny")
    }
    found = []
    missing = [rule for rule in ASK if rule not in rules["ask"]]
    gates = [rule for rule in missing if ".sdd/bin/sdd" in rule]
    git = [rule for rule in missing if rule not in gates]
    if gates:
        found.append(Finding(FAIL, f"sdd gates do not prompt: {gates}", "run `sdd init` again"))
    else:
        found.append(Finding(OK, "approve, trust, start and resume prompt you"))
    if git:
        found.append(Finding(WARN, f"these run without asking: {git}", "fine if you chose it"))
    if any(rule not in rules["deny"] for rule in DENY):
        found.append(Finding(WARN, "deny rules for .sdd/ are missing", "run `sdd init` again"))
    if not any((s.get("sandbox") or {}).get("enabled") for s in settings):
        found.append(
            Finding(
                WARN,
                "sandbox is off: `sdd check` runs agent-written tests as you",
                'enable Claude Code sandboxing ("sandbox": {"enabled": true})',
            )
        )
    for var in ("SDD_HOME", "SDD_PYTHON"):
        if any(var in (s.get("env") or {}) for s in settings):
            found.append(
                Finding(WARN, f"{var} is set in Claude settings", "make sure you set it yourself")
            )
    modes = {s.get("permissions", {}).get("defaultMode") for s in settings}
    if "bypassPermissions" in modes:
        found.append(
            Finding(FAIL, "defaultMode is bypassPermissions", "gates do not prompt; change it")
        )
    return found


def _install(root: Path) -> list[Finding]:
    found = []
    shim = root / SHIM
    if shim.exists():
        found.append(Finding(OK, f"{SHIM.as_posix()} exists"))
    else:
        found.append(Finding(WARN, f"{SHIM.as_posix()} missing", "run `sdd init` or restart"))
    gitignore = root / ".gitignore"
    text = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    if ".sdd" not in text:
        found.append(Finding(WARN, ".sdd/ is not git-ignored", "run `sdd init` again"))
    return found


def _graph(cfg: cfg_mod.Config) -> Finding:
    if not cfg.graphify_auto:
        return Finding(
            WARN, "code graph is off ([graphify] auto = false)", "agents read more files"
        )
    if graph.find_graphify() is None:
        return Finding(WARN, "graphify not installed yet", "`sdd graph sync` installs it")
    status = graph.graph_status(cfg.root)
    if status == "fresh":
        return Finding(OK, "code graph is up to date")
    return Finding(WARN, f"code graph is {status}", "`sdd graph sync` (also runs at session start)")


def _tools() -> list[Finding]:
    found = []
    if shutil.which("gh"):
        found.append(Finding(OK, "GitHub CLI (gh) found"))
    else:
        found.append(Finding(WARN, "GitHub CLI (gh) not found", "install it to open PRs on ship"))
    if graph.find_graphify() is None and not (shutil.which("uv") or shutil.which("pipx")):
        found.append(
            Finding(WARN, "neither uv nor pipx found", "graphify falls back to pip --user")
        )
    return found


def _remote() -> list[Finding]:
    if not prereqs.phone_control_configured():
        return [Finding(OK, "phone control not set up (optional: `/sdd-pilot:remote`)")]
    found = []
    if prereqs.find_bun() is None:
        found.append(Finding(FAIL, "Bun is missing; Telegram needs it", "`sdd install bun`"))
    elif not prereqs.bun_on_path():
        fix = "restart the terminal and Claude Code"
        found.append(Finding(WARN, "Bun is installed but not on PATH", fix))
    else:
        found.append(Finding(OK, "Bun found"))
    status = telegram_status()
    if status["ready"]:
        found.append(Finding(OK, "Telegram phone control ready"))
    else:
        problems = "; ".join(status["problems"])
        found.append(Finding(WARN, f"Telegram: {problems}", "`/sdd-pilot:remote`"))
    return found


def run_doctor(start: Path, extra: list[Finding] | None = None) -> list[Finding]:
    found = [_python()]
    try:
        cfg = cfg_mod.load(start)
    except ValueError as error:
        return [*found, Finding(FAIL, str(error), "run `/sdd-pilot:init`")]
    found.append(_git(cfg.root))
    found += _checks(cfg)
    found += _permissions(cfg.root)
    found += _install(cfg.root)
    found.append(_graph(cfg))
    found += extra or []
    found += _tools()
    found += _remote()
    return found


def format_findings(found: list[Finding]) -> str:
    lines = []
    for item in found:
        fix = f"  -> {item.fix}" if item.fix and item.level != OK else ""
        lines.append(f"{item.level:<4} {item.what}{fix}")
    fails = sum(item.level == FAIL for item in found)
    warns = sum(item.level == WARN for item in found)
    lines.append(f"SDD DOCTOR: {'FAIL' if fails else 'OK'} ({fails} to fix, {warns} warnings)")
    return "\n".join(lines)
