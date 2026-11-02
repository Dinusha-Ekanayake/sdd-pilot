from pathlib import Path

import pytest

from sdd_pilot import config

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


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    spec = tmp_path / "specs" / "009-demo"
    spec.mkdir(parents=True)
    (spec / "tasks.md").write_text(TASKS, encoding="utf-8")
    (spec / "spec.md").write_text(SPEC, encoding="utf-8")
    (spec / "plan.md").write_text(PLAN, encoding="utf-8")
    (tmp_path / "sdd.toml").write_text("[brief]\ngraphify = false\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def cfg(repo: Path) -> config.Config:
    return config.load(repo)


def tasks_file(repo: Path) -> Path:
    return repo / "specs" / "009-demo" / "tasks.md"
