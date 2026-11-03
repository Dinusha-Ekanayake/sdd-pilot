import subprocess
from pathlib import Path

import pytest

from sdd_pilot.worktree import fingerprint


def test_fingerprint_without_git_follows_files_and_skips_run_state(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    before = fingerprint(tmp_path)
    (tmp_path / ".sdd").mkdir()
    (tmp_path / ".sdd" / "state.json").write_text("{}")
    assert fingerprint(tmp_path) == before
    (tmp_path / "a.py").write_text("x = 2\n")
    assert fingerprint(tmp_path) != before


def test_fingerprint_exclude(tmp_path: Path) -> None:
    (tmp_path / "tasks.md").write_text("[ ]")
    before = fingerprint(tmp_path, exclude=("tasks.md",))
    (tmp_path / "tasks.md").write_text("[x]")
    assert fingerprint(tmp_path, exclude=("tasks.md",)) == before


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "tasks.md").write_text("[ ]\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "init")
    return tmp_path


def test_fingerprint_in_git_sees_tracked_and_untracked_changes(git_repo: Path) -> None:
    clean = fingerprint(git_repo, exclude=("tasks.md",))
    (git_repo / "tasks.md").write_text("[x]\n")
    assert fingerprint(git_repo, exclude=("tasks.md",)) == clean
    (git_repo / "new.py").write_text("y = 1\n")
    untracked = fingerprint(git_repo, exclude=("tasks.md",))
    assert untracked != clean
    (git_repo / "a.py").write_text("x = 2\n")
    assert fingerprint(git_repo, exclude=("tasks.md",)) not in (clean, untracked)
