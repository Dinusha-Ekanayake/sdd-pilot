# Contributing

```bash
python -m venv .venv
.venv/bin/pip install pytest pytest-cov ruff mypy      # Windows: .venv/Scripts/pip
bash bin/sdd init                                       # the repo uses itself
bash .sdd/bin/sdd trust                                 # once, after reviewing sdd.toml
bash .sdd/bin/sdd check                                 # lint, format, types, tests (85% coverage floor)
```

- Standard library only for runtime code. No runtime dependencies.
- Python 3.11+, strict mypy, ruff.
- Add a test for every change; the launcher, hooks and CLI have end-to-end tests that run through `bash`.
- Keep shell scripts LF (`.gitattributes` enforces it) and presets ASCII-only.
- Commit messages: Conventional Commits (`feat|fix|perf|docs|test|ci|chore: summary`).
- Pinned tools: `BUN_VERSION` (`specsteward/prereqs.py`) and `GRAPHIFY_VERSION`
  (`specsteward/config.py`). Bump them deliberately, after reading the release notes, in a
  commit of their own.
- Releases: bump `.claude-plugin/plugin.json` and `pyproject.toml` together and date the
  `CHANGELOG.md` section; a test checks that they agree.
- Changing an agent or skill prompt? Say what failure it fixes and, if possible, add a unit test for the script side.
