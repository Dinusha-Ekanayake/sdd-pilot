"""Trust and approval records kept outside the repository.

A cloned repository can ship any ``sdd.toml``, and its ``[[check]]`` and ``[format]``
commands run without a permission prompt. So sdd-pilot only runs them once the user has
trusted that exact file (``sdd trust``, behind an ``ask`` rule). Spec approvals are stored
the same way, bound to the content of ``spec.md``.

The store lives in the user's home (``~/.claude/sdd-pilot/trust.json``, or ``$SDD_HOME``),
not in the project, so agents editing project files cannot forge it.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from sdd_pilot.config import CONFIG_FILE

STORE_NAME = "trust.json"


def store_path() -> Path:
    home = os.environ.get("SDD_HOME")
    base = Path(home) if home else Path.home() / ".claude" / "sdd-pilot"
    return base / STORE_NAME


def file_hash(path: Path) -> str | None:
    """sha256 of the file's bytes, or None when it does not exist."""
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _key(root: Path) -> str:
    return root.resolve().as_posix().lower() if os.name == "nt" else root.resolve().as_posix()


def _load() -> dict[str, Any]:
    path = store_path()
    if not path.exists():
        return {"projects": {}}
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"projects": {}}
    data.setdefault("projects", {})
    return data


def _save(data: dict[str, Any]) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _project(data: dict[str, Any], root: Path) -> dict[str, Any]:
    entry: dict[str, Any] = data["projects"].setdefault(_key(root), {})
    return entry


def _read(root: Path) -> dict[str, Any]:
    entry: dict[str, Any] = _load()["projects"].get(_key(root), {})
    return entry


def trust_config(root: Path) -> str:
    """Record the current ``sdd.toml`` as trusted and return its hash."""
    digest = file_hash(root / CONFIG_FILE)
    if digest is None:
        raise ValueError(f"no {CONFIG_FILE} in {root}")
    data = _load()
    _project(data, root)["config"] = digest
    _save(data)
    return digest


def config_trusted(root: Path) -> bool:
    digest = file_hash(root / CONFIG_FILE)
    return digest is not None and _read(root).get("config") == digest


def record_approval(root: Path, spec: str, digest: str) -> None:
    data = _load()
    _project(data, root).setdefault("approvals", {})[spec] = digest
    _save(data)


def approved_hash(root: Path, spec: str) -> str | None:
    value = _read(root).get("approvals", {}).get(spec)
    return str(value) if value else None


def record_guard(root: Path, files: tuple[str, ...]) -> None:
    """Remember the gate config files as they are now (missing files included)."""
    data = _load()
    _project(data, root)["guard"] = {rel: file_hash(root / rel) for rel in files}
    _save(data)


def changed_guard(root: Path, files: tuple[str, ...]) -> list[str]:
    """Gate config files that differ from the recorded baseline."""
    baseline = _read(root).get("guard")
    if baseline is None:
        return []
    return [rel for rel in files if baseline.get(rel) != file_hash(root / rel)]
