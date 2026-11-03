# Changelog

## Unreleased

### Security
- `sdd.toml` commands (gate and format hook) run only after `sdd trust`; any change makes it untrusted again.
- Spec approval is bound to the sha256 of `spec.md`; hand-edited or since-changed specs do not count as approved.
- `sdd start`, `sdd resume` and `sdd trust` are permission prompts; `start` refuses while a run is active.
- A PreToolUse hook and deny rules stop file edits to `.sdd/` and the trust store.
- Changing gate config files during a run fails the check; the reviewer flags gate weakening.
- Every agent is told to treat repository content as data.

### Added
- `sdd done` requires a passing gate and a clean review of the current code; failures are recorded against the group in flight; a SubagentStop hook counts agents for the cap.
- `sdd init` detects the stack (Python, Node, Go, Rust, Makefile) and the project's own tools; `{python}` resolves per machine.
- `sdd doctor` checks the setup and prints fixes.
- `sdd statusline`, `sdd init --statusline`, and a read-only `.sdd/dashboard.html`.
- Automatic graphify code graph: installed (pinned), built and refreshed in the background, on every machine; `sdd graph status|sync`.
- `[review] skip = ["low"]` to leave low-risk tasks to the final review.

### Fixed
- Hooks never break the session; the launcher skips Python in projects without `sdd.toml`.
- Check steps have a timeout; state is written atomically; invalid regexes fail at load time.
- Task tables: `|` inside backticks, and a Status column that is not last.
- Briefs: flat package layouts, `async def`, syntax errors, size caps; static rules moved to the agent prompt.

## 0.1.0 - Unreleased
- Plugin with planner, implementer, reviewer and clerk agents; `run`, `init` and `remote` skills.
- `sdd` CLI: gate, briefs, run state with caps, approvals log, hooks.
- `sdd.toml` configuration with python, node and generic presets.
- Phone approvals through the official Telegram channel plugin.
