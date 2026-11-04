from pathlib import Path

import pytest

from specsteward import config, trust

TASKS = """\
# Tasks 009: demo

| ID | Task | Test | Risk | Status |
|---|---|---|---|---|
| T-009-01 | `configs/x.yaml` loader | loads | low | [x] |
| T-009-02 | `features/demo.make_demo` | values | high | [ ] |
| T-009-03 | `features/demo` leakage | future rows | high | [ ] |
| T-009-04 | `models/demo.Scorer` | scores | high | [ ] |
| T-009-05 | helper | shape | low | [ ] |
| T-009-06 | real data run | files | human | [ ] |
"""
SPEC = """\
# Spec 009: demo
- **Status:** Approved (2026-11-02)
- REQ-009-01: Features use only past rows.
- [ ] AC-01: tests pass.
"""
PLAN = "| `src/demo/demo.py` | `make_demo(df)` builds features |\nunrelated line\n"


@pytest.fixture(autouse=True)
def git_stops_at_the_test_folder(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never let git find a repository above the test folders (a home folder may be one)."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path_factory.getbasetemp()))


@pytest.fixture(autouse=True)
def trust_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the trust store out of the real home directory."""
    home = tmp_path_factory.mktemp("sdd-home")
    monkeypatch.setenv("SDD_HOME", str(home))
    return home


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    spec = tmp_path / "specs" / "009-demo"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(TASKS, encoding="utf-8")
    (spec / "spec.md").write_text(SPEC, encoding="utf-8")
    (spec / "plan.md").write_text(PLAN, encoding="utf-8")
    (tmp_path / "sdd.toml").write_text("[brief]\ngraphify = false\n", encoding="utf-8")
    trust.trust_config(tmp_path)
    from specsteward.state import approval_digest

    trust.record_approval(tmp_path, "009", approval_digest(spec))
    return tmp_path


def write_config(repo: Path, text: str) -> config.Config:
    """Replace sdd.toml, trust it (as the user would) and load it."""
    (repo / "sdd.toml").write_text(text, encoding="utf-8")
    trust.trust_config(repo)
    return config.load(repo)


@pytest.fixture
def cfg(repo: Path) -> config.Config:
    return config.load(repo)


def tasks_file(repo: Path) -> Path:
    return repo / "specs" / "009-demo" / "tasks.md"


def tick(cfg: config.Config, task_id: str, human: bool = False) -> None:
    """Tick a task as the loop would: its gate passed and its review was clean for this tree."""
    from specsteward import state as run_state

    state = run_state.require(cfg.root)
    now = run_state.tree(cfg.root, state)
    state["gate"] = {"group": [task_id], "passed": now, "reviewed": now}
    run_state.save(cfg.root, state)
    run_state.complete(cfg, task_id, human)


@pytest.fixture(autouse=True)
def no_background_graph(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Tests never install graphify or spawn a background build; they record the request."""
    from specsteward import graph

    calls: list[Path] = []

    def fake_start(root: Path, entry: Path) -> bool:
        calls.append(root)
        return True

    from specsteward import prereqs

    monkeypatch.setattr(
        prereqs, "_real_bun_start", prereqs.start_background_bun_install, raising=False
    )
    monkeypatch.setattr(prereqs, "start_background_bun_install", lambda entry: False)
    monkeypatch.setattr(graph, "_real_start", graph.start_background_sync, raising=False)
    monkeypatch.setattr(graph, "start_background_sync", fake_start)
    return calls
