# Contributing

```bash
python -m venv .venv
.venv/bin/pip install pytest pytest-cov ruff mypy      # Windows: .venv/Scripts/pip
bash bin/sdd init --preset python                       # the repo uses itself
bash .sdd/bin/sdd check                                 # lint, format, types, tests (85% coverage floor)
```

- Standard library only for runtime code. No runtime dependencies.
- Python 3.11+, strict mypy, ruff.
- Add a test for every change; the launcher, hooks and CLI have end-to-end tests that run through `bash`.
- Keep shell scripts LF (`.gitattributes` enforces it) and presets ASCII-only.
- Commit messages: `feat|fix|docs|test|chore: summary`.
- Changing an agent or skill prompt? Say what failure it fixes and, if possible, add a unit test for the script side.
