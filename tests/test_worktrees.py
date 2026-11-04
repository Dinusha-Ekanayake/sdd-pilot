"""Parallel runs: git worktrees share trust and approvals, but not run state."""

import subprocess
from pathlib import Path

import pytest

from specsteward import config, trust
from specsteward import state as run_state
from specsteward.__main__ import main


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    return proc.stdout.strip()


@pytest.fixture
def git_repo(repo: Path) -> Path:
    """The demo repository, committed, on its feature branch."""
    _git(repo, "init", "-q", "-b", "feature/009-demo")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / ".gitignore").write_text(".sdd/\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    trust.repo_root.cache_clear()
    return repo


def test_worktree_shares_trust_and_approval_but_not_run_state(git_repo: Path) -> None:
    cfg = config.load(git_repo)
    _git(git_repo, "checkout", "-q", "-b", "main")
    target = run_state.create_worktree(cfg, "009")
    assert target == git_repo.parent / f"{git_repo.name}-009"
    assert _git(target, "branch", "--show-current") == "feature/009-demo"
    trust.repo_root.cache_clear()
    assert trust.repo_root(target).resolve() == git_repo.resolve()
    assert trust.config_trusted(target)  # trusted once, in the main checkout
    wt_cfg = config.load(target)
    run_state.start(wt_cfg, "009")  # approved in the main checkout too
    assert run_state.load(target) is not None
    assert run_state.load(git_repo) is None  # each worktree has its own run


def test_uncommitted_spec_and_config_are_copied(git_repo: Path) -> None:
    spec = git_repo / "specs" / "010-new"
    spec.mkdir()
    (spec / "spec.md").write_text("# Spec 010\n- **Status:** Draft\n")
    cfg = config.load(git_repo)
    target = run_state.create_worktree(cfg, "010")
    assert (target / "specs" / "010-new" / "spec.md").read_text() == (spec / "spec.md").read_text()
    assert _git(target, "branch", "--show-current") == "feature/010-new"


def test_fix_specs_get_a_fix_branch_and_an_existing_target_is_refused(git_repo: Path) -> None:
    spec = git_repo / "specs" / "011-fix-crash"
    spec.mkdir()
    (spec / "spec.md").write_text("x")
    cfg = config.load(git_repo)
    target = run_state.create_worktree(cfg, "011")
    assert _git(target, "branch", "--show-current") == "fix/011-crash"
    with pytest.raises(ValueError, match="already exists"):
        run_state.create_worktree(cfg, "011")


def test_several_trusted_configs_coexist(git_repo: Path) -> None:
    original = (git_repo / "sdd.toml").read_text()
    (git_repo / "sdd.toml").write_text(original + "# branch b\n")
    trust.trust_config(git_repo)
    assert trust.config_trusted(git_repo)
    (git_repo / "sdd.toml").write_text(original)
    assert trust.config_trusted(git_repo)  # the first version is still trusted


def test_old_single_config_record_still_counts(repo: Path) -> None:
    store = trust.store_path()
    text = store.read_text()
    digest = trust.file_hash(repo / "sdd.toml")
    store.write_text(
        text.replace(f'"configs": [\n        "{digest}"\n      ]', f'"config": "{digest}"')
    )
    assert '"config":' in store.read_text() and trust.config_trusted(repo)


def test_cli_worktree(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(git_repo))
    _git(git_repo, "checkout", "-q", "-b", "main")
    assert main(["worktree", "009"]) == 0
    out = capsys.readouterr().out
    assert "worktree ready" in out and "/specsteward:run 009" in out
    assert (git_repo.parent / f"{git_repo.name}-009" / ".sdd" / "bin" / "sdd").is_file()
