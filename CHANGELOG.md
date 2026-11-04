# Changelog

## 0.2.0 - 2026-11-04

### Upgrading from 0.1.0
- Run `/sdd-pilot:init` (or `bash .sdd/bin/sdd init`) once: it adds the new permission rules and `specs/constitution.md`, and keeps your `sdd.toml`.
- Review your `sdd.toml`, then run `bash .sdd/bin/sdd trust`. Until then `sdd check` and the format hook run nothing.
- Approve specs again (`sdd approve <NNN>`): approvals now cover the spec, plan and task table.
- A run started with 0.1.0 is not picked up; start it again with `sdd approve <NNN> --start` or `sdd start <NNN>`.
- `sdd done` now needs a passing `sdd check` and a clean `sdd review` of the current code first.
- Claude can no longer edit `.claude/settings*.json` with file tools in an sdd project; change those by hand or with `/config`.
- Run `bash .sdd/bin/sdd doctor` to confirm the setup.

### Security
- `sdd.toml` commands (the gate and the format hook) run only after `sdd trust`, which is a permission prompt; any change makes the file untrusted again. The trust store lives outside the repository (`~/.claude/sdd-pilot/`).
- Spec approval is bound to a hash of `spec.md`, `plan.md` and the task definitions. Task statuses are recorded by `sdd start` and `sdd done`, so hand-ticked, deleted or re-risked rows halt the run.
- `sdd start`, `sdd resume` and `sdd trust` are permission prompts; `start` refuses while a run is active; `sdd init --force` never trusts the config it replaces.
- A PreToolUse hook and deny rules block file edits to `.sdd/`, the trust store and `.claude/settings*.json`, matching paths by file identity.
- `sdd done` requires a passing gate and a clean review recorded for the current tree, fingerprinted before and after the gate.
- Changing gate config files during a run fails the check; the reviewer flags new skips, ignores and lowered thresholds.
- graphify is installed only for a trusted `sdd.toml`, from the home directory in isolated mode.
- Repository-shipped virtual environments, symlinks and run state are ignored or refused.
- Every agent prompt treats repository content as data, not instructions.
- `sdd doctor` warns when Claude Code sandboxing is off, since the gate runs agent-written tests as you.

### Added
- `sdd init` detects the stack (Python, Node, Go, Rust, Makefile) and the project's own lint, type and test tools, so `sdd.toml` needs no editing; `{python}` resolves per machine.
- `sdd doctor`: checks every prerequisite and the setup, and prints a fix for each problem.
- Automatic graphify code graph, installed (pinned), built and refreshed in the background on every machine; sessions are told to query it before reading files. `sdd graph status|sync`.
- Automatic Bun install (pinned, per user, no admin rights) once phone control is set up; `sdd install bun`. The launcher falls back to a uv-managed Python when no Python 3.11+ is installed.
- `sdd statusline` (`sdd init --statusline`) and a read-only `.sdd/dashboard.html`.
- `sdd analyze`: scripted checks of spec, plan and tasks (clarifications, placeholders, requirement coverage, vague wording, plan paths); `sdd approve` refuses CRITICAL findings unless `--anyway`.
- Project constitution (`specs/constitution.md`): its MUST rules go into every brief; violations are CRITICAL in review.
- Clarify step: the planner asks up to five `[NEEDS CLARIFICATION]` questions before approval; answer with `answer <NNN>: ...`, also from the phone.
- `sdd approve <NNN> --start`: approve and start in one permission prompt.
- `[review] skip = ["low"]` to leave low-risk tasks to the final branch review.
- Token meter: the run's tokens (session and subagents) in `sdd status`, the status line and the dashboard, and an optional `[limits] max_tokens` budget that halts the run.
- Go and Rust presets.

### Changed
- Static rules and the report format moved from every brief into the implementer's agent prompt (about 140 words less per brief).
- Subagent runs are counted by a SubagentStop hook as well as `sdd agent`; the cap uses the higher count.
- `sdd check` records failures against the group in flight without `--task`.

### Fixed
- Hooks never break the session, and the launcher skips Python in projects without `sdd.toml`.
- Concurrent sessions no longer overwrite each other's trust-store records (locked writes).
- Check steps have a timeout; state is written atomically; invalid regexes fail at load time.
- `init --specs-dir` is written to the generated `sdd.toml`.
- Task tables: `|` inside backticks, and a Status column that is not last.
- Briefs: flat package layouts, `async def`, syntax errors, size caps.

Thanks to GitHub's [Spec Kit](https://github.com/github/spec-kit) for the ideas behind clarify, analyze and the constitution.

## 0.1.0 - 2026-11-02
- Plugin with planner, implementer, reviewer and clerk agents; `run`, `init` and `remote` skills.
- `sdd` CLI: gate, briefs, run state with caps, approvals log, hooks.
- `sdd.toml` configuration with python, node and generic presets.
- Phone approvals through the official Telegram channel plugin.
