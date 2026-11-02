# Configuration (`sdd.toml`)

`sdd init` writes this file at the repository root from a preset. Every section is optional; the defaults are shown.

## `[project]`

| Key | Default | Meaning |
|---|---|---|
| `specs_dir` | `"specs"` | Folder holding `<NNN>-<slug>/spec.md`, `plan.md`, `tasks.md` |
| `branch_prefix` | `"feature/{spec}-"` | `sdd start 003` requires a branch starting with `feature/003-`. Set `""` to turn the check off |
| `status_regex` | `(\*\*Status:\*\*\s*)([^\n]*)` | Finds the status line in `spec.md`. Group 1 is kept, group 2 is replaced on approval |
| `approved_word` | `"Approved"` | A spec counts as approved when its status starts with this |

## `[[check]]` (the quality gate)

One table per step, run in order. Commands are argument lists, not shell strings.

```toml
[[check]]
name = "tests"
cmd = ["npm", "test", "--silent"]
keep = '(FAIL|Error:)'     # regex: which output lines to show when it fails
```

- A command is looked up relative to the repository first, then on `PATH` (so `npm` finds `npm.cmd` on Windows).
- If a step fails and `keep` matches nothing, the last 25 lines are shown.
- Lines like `TOTAL ... 96%` (coverage.py) or `All files` (Jest) are shown as a coverage line.
- The gate prints `SDD CHECK: PASS` or `FAIL` plus a `SIGNATURE`. The same signature twice halts the run.

## `[format]`

Formatters run after every file Claude edits, by suffix. `{file}` is the edited path.

```toml
[format]
".py" = [["ruff", "format", "{file}"], ["ruff", "check", "--fix", "--select", "I", "{file}"]]
```

## `[wording]`

```toml
[wording]
banned = ["failure predicted", '\bguaranteed\b']   # case-insensitive regexes
negations = ["not", "never", "no"]                 # a match right after one of these is allowed
scan = ["src", "docs"]
suffixes = [".py", ".md"]
allow_marker = "sdd: allow-wording"                # put this on a line to allow it
```

An empty `banned` list turns the scan off.

## `[models]`

Which model reviews tasks of each risk. The planner is Opus, the implementer Sonnet and the clerk Haiku (set in `agents/*.md`).

```toml
[models]
low = "sonnet"
high = "opus"
human = "opus"
```

## `[limits]`

| Key | Default | Halts when |
|---|---|---|
| `max_review_rounds` | 2 | a review still has open findings on the Nth round |
| `max_fix_attempts` | 3 | more than N gate failures for a task |
| `max_agent_runs` | 60 | more than N subagent runs in one spec |
| `restart_after_tasks` | 4 | (not a halt) start a fresh implementer after N completed tasks |

## `[groups]`

`max_size` (default 3) low-risk tasks, and `max_high` (default 2) high-risk tasks, go to the implementer in one run. `human` tasks always run alone.

## `[brief]`

| Key | Meaning |
|---|---|
| `helper_files` | Files always shown to the implementer (signatures only), for example `["tests/conftest.py"]` |
| `path_roots` | Top-level folders recognised when a plan names a path |
| `graphify` | Add related nodes from a [graphify](https://github.com/Graphify-Labs/graphify) graph when `graphify-out/` exists |

## Permission rules written by `init`

`.claude/settings.json` gets, without removing anything already there:

- `allow`: `bash .sdd/bin/sdd` (everything except `approve`), `git status`, `git diff`, `git log`, `git rev-parse`
- `ask`: `bash .sdd/bin/sdd approve`, `git commit`, `git push`, `gh pr create`, `gh pr merge`

`ask` wins over `allow`, so the gates always prompt.
