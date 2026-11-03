"""``sdd init``: set up a project with a config preset, templates and permission rules."""

import json
import shutil
from pathlib import Path
from typing import Any

from sdd_pilot import trust
from sdd_pilot.config import CONFIG_FILE

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
PRESETS = ("python", "node", "generic")
SDD = "bash .sdd/bin/sdd"

ALLOW = [
    f"Bash({SDD}:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git rev-parse:*)",
]
# Human gates. "ask" beats "allow", so these always prompt, and a channel plugin
# with permission relay (for example Telegram) can show the prompt on a phone.
# Everything that approves, trusts, or resets a cap is here; halting and stopping are not.
ASK = [
    f"Bash({SDD} approve:*)",
    f"Bash({SDD} trust:*)",
    f"Bash({SDD} start:*)",  # a restart would reset the caps
    f"Bash({SDD} resume:*)",  # clears a halt and the per-task counters
    "Bash(git commit:*)",
    "Bash(git push:*)",
    "Bash(gh pr create:*)",
    "Bash(gh pr merge:*)",
]

# Defence in depth next to the PreToolUse guard hook: file tools never edit run state
# or the trust store. "Edit" rules cover every built-in file-editing tool.
DENY = [
    "Edit(.sdd/**)",
    "Edit(~/.claude/sdd-pilot/**)",
]


def _python_exe(root: Path) -> str:
    for candidate in (".venv/Scripts/python.exe", ".venv/bin/python", "venv/bin/python"):
        if (root / candidate).exists():
            return candidate
    return "python"


def render_config(root: Path, preset: str) -> str:
    if preset not in PRESETS:
        raise ValueError(f"preset must be one of {PRESETS}")
    text = (TEMPLATES / f"sdd.{preset}.toml").read_text(encoding="utf-8")
    return text.replace("{python}", _python_exe(root))


def _merge_settings(path: Path) -> list[str]:
    settings: dict[str, Any] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    permissions = settings.setdefault("permissions", {})
    added = []
    for key, rules in (("allow", ALLOW), ("ask", ASK), ("deny", DENY)):
        existing = permissions.setdefault(key, [])
        for rule in rules:
            if rule not in existing:
                existing.append(rule)
                added.append(f"{key}: {rule}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return added


def _ensure_gitignore(root: Path) -> bool:
    path = root / ".gitignore"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if any(line.strip() in (".sdd", ".sdd/") for line in text.splitlines()):
        return False
    prefix = "" if not text or text.endswith("\n") else "\n"
    path.write_text(f"{text}{prefix}\n# sdd-pilot run state\n.sdd/\n", encoding="utf-8")
    return True


def init_project(
    root: Path, preset: str, specs_dir: str = "specs", force: bool = False
) -> list[str]:
    """Create what is missing and report each change. Never overwrites without ``force``."""
    done = []
    config = root / CONFIG_FILE
    if config.exists() and not force:
        done.append(f"kept existing {CONFIG_FILE}")
        if not trust.config_trusted(root):
            done.append(f"review {CONFIG_FILE}, then run `{SDD} trust` before the first check")
    else:
        config.write_text(render_config(root, preset), encoding="utf-8")
        trust.trust_config(root)  # the user asked for this file, so it starts trusted
        done.append(f"wrote {CONFIG_FILE} ({preset} preset, trusted)")
    template_dir = root / specs_dir / "_template"
    template_dir.mkdir(parents=True, exist_ok=True)
    for name in ("spec.md", "plan.md", "tasks.md"):
        target = template_dir / name
        if not target.exists() or force:
            shutil.copyfile(TEMPLATES / name, target)
            done.append(f"wrote {target.relative_to(root).as_posix()}")
    if _ensure_gitignore(root):
        done.append("added .sdd/ to .gitignore")
    done += [f"permission {rule}" for rule in _merge_settings(root / ".claude" / "settings.json")]
    return done
