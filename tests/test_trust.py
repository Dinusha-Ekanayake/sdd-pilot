from pathlib import Path

import pytest

from sdd_pilot import trust


def test_store_lives_in_sdd_home_not_the_project(repo: Path, trust_home: Path) -> None:
    assert trust.store_path().parent == trust_home
    assert not (repo / trust.STORE_NAME).exists()


def test_config_trust_follows_file_content(repo: Path) -> None:
    assert trust.config_trusted(repo)
    (repo / "sdd.toml").write_text("[project]\n")
    assert not trust.config_trusted(repo)
    trust.trust_config(repo)
    assert trust.config_trusted(repo)


def test_trust_needs_a_config(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no sdd.toml"):
        trust.trust_config(tmp_path)
    assert not trust.config_trusted(tmp_path)


def test_trust_is_per_project(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    other = tmp_path_factory.mktemp("other")
    (other / "sdd.toml").write_bytes((repo / "sdd.toml").read_bytes())
    assert not trust.config_trusted(other)  # same content, different repository


def test_approvals_round_trip(repo: Path) -> None:
    assert trust.approved_hash(repo, "010") is None
    trust.record_approval(repo, "010", "abc")
    assert trust.approved_hash(repo, "010") == "abc"


def test_guard_reports_changed_created_and_deleted_files(repo: Path) -> None:
    (repo / "a.toml").write_text("x")
    (repo / "b.toml").write_text("y")
    files = ("a.toml", "b.toml", "c.toml")
    assert trust.changed_guard(repo, files) == []  # no baseline yet
    trust.record_guard(repo, files)
    assert trust.changed_guard(repo, files) == []
    (repo / "a.toml").write_text("changed")
    (repo / "b.toml").unlink()
    (repo / "c.toml").write_text("new")
    assert trust.changed_guard(repo, files) == ["a.toml", "b.toml", "c.toml"]


def test_corrupt_store_counts_as_untrusted(repo: Path) -> None:
    trust.store_path().write_text("{not json")
    assert not trust.config_trusted(repo)
    trust.trust_config(repo)  # and it recovers
    assert trust.config_trusted(repo)
