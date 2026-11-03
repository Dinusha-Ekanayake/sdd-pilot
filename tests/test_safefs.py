from pathlib import Path

import pytest

from sdd_pilot import graph
from sdd_pilot.hooks import write_shim
from sdd_pilot.safefs import ensure_safe


def _symlink(link: Path, target: Path, is_dir: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_dir)
    except OSError:
        pytest.skip("symlinks not permitted here")


def test_plain_paths_are_fine(tmp_path: Path) -> None:
    ensure_safe(tmp_path, tmp_path / ".sdd" / "state.json")  # need not exist yet


def test_outside_the_project_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside the project"):
        ensure_safe(tmp_path / "repo", tmp_path / "elsewhere.txt")


def test_symlinked_run_folder_is_refused(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    victim = tmp_path_factory.mktemp("victim")
    _symlink(tmp_path / ".sdd", victim, is_dir=True)
    with pytest.raises(ValueError, match="through a symlink: .sdd"):
        write_shim(tmp_path, Path("launcher"))
    assert list(victim.iterdir()) == []


def test_dangling_ignore_file_symlink_is_refused(
    tmp_path: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    profile = tmp_path_factory.mktemp("home") / ".bashrc"
    _symlink(tmp_path / graph.IGNORE_FILE, profile)
    with pytest.raises(ValueError, match="through a symlink"):
        graph.ensure_ignores(tmp_path)
    assert not profile.exists()


def test_refusal_without_real_symlinks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / ".sdd"
    real = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == run_dir or real(self))
    with pytest.raises(ValueError, match="through a symlink: .sdd"):
        ensure_safe(tmp_path, run_dir / "state.json")
