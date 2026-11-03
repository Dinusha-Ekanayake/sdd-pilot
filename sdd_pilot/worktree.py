"""A fingerprint of the working tree, so a gate result can be tied to the code it saw.

``sdd done`` only ticks a task when the last passing check and the last clean review were
both recorded for the code as it is now. The fingerprint covers tracked changes and
untracked files; run state and the task table being ticked are left out.
"""

import hashlib
import subprocess
from collections.abc import Callable
from pathlib import Path

SKIP_DIRS = {".git", ".sdd", ".venv", "venv", "node_modules", "__pycache__", "graphify-out"}
SKIP_DIRS |= {".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build", "target"}


def _git(root: Path, *args: str) -> bytes | None:
    try:
        proc = subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def _hash_files(root: Path, paths: list[Path], update: Callable[[bytes], None]) -> None:
    for path in sorted(paths):
        update(path.relative_to(root).as_posix().encode() + b"\0")
        try:
            update(path.read_bytes())
        except OSError:
            update(b"<unreadable>")
        update(b"\0")


def fingerprint(root: Path, exclude: tuple[str, ...] = ()) -> str:
    """sha256 of the uncommitted state of ``root``; ``exclude`` lists relative paths."""
    digest = hashlib.sha256()
    excluded = set(exclude)
    pathspec = [".", *(f":(exclude){rel}" for rel in exclude)]
    diff = _git(root, "diff", "HEAD", "--binary", "--", *pathspec)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z", "--", *pathspec)
    if diff is not None and untracked is not None:
        digest.update(b"git\0" + diff)
        names = [name for name in untracked.decode("utf-8", "replace").split("\0") if name]
        _hash_files(root, [root / name for name in names if name not in excluded], digest.update)
        return digest.hexdigest()
    # Not a git repository, or no commit yet: hash every file outside the skipped folders.
    files = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and not SKIP_DIRS & set(path.relative_to(root).parts)
        and path.relative_to(root).as_posix() not in excluded
    ]
    digest.update(b"files\0")
    _hash_files(root, files, digest.update)
    return digest.hexdigest()
