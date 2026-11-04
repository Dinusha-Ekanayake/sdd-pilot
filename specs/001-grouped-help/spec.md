# Spec 001: Grouped `sdd --help`

- **Status:** Approved (2026-11-04)
- **Branch:** `feature/001-grouped-help`
- **Depends on:**

## Problem / why
`sdd --help` prints one flat list of 24 public commands in the order they were added to
`_parser` in `specsteward/__main__.py`. A new user who wants to set a project up or look at a
run has to read the whole list, and commands only the agents call during a run (`agent`,
`review`, `done`, `converge`) sit between the ones people type (`init`, `approve`, `status`).
Grouping the list by purpose lets people find the right command quickly.

## Scope
### In scope
- The command list printed by `sdd --help` (and `sdd -h`), shown under five headed groups:
  setup, specs, running a spec, views and status, used by the agents during a run.
- One table in `specsteward/__main__.py` that names each public command, its group and its
  one-line help, so the list cannot drift from the commands that exist.
- Tests for the grouped output.

### Non-goals
- No change to any command's behaviour, arguments, defaults, exit codes or per-command help
  (`sdd init --help` stays as it is).
- No renaming, adding or removing of commands.
- No change to the unknown-command error message or to `--version`.
- No new dependency (constitution: standard library only).
- No guided "start here" walkthrough in the help; the README and `docs/setup-guide.md` stay
  the place for that.

## Requirements
- REQ-001-01: `sdd --help` lists the public commands under five headings, in this order:
  "setup", "specs", "running a spec", "views and status", "used by the agents during a run".
  Each heading is followed by its
  commands, one per line, with the command name and its existing one-line help text.
- REQ-001-02: Every public command (every subcommand not in `HOOKS`) appears in exactly one
  group, exactly once. A test fails if a command is added to the parser without a group or
  a group names a command that does not exist.
- REQ-001-03: The internal `hook-*` commands in `HOOKS` never appear in `sdd --help`, and the
  unknown-command error still does not mention them.
- REQ-001-04: The grouping is display-only: every command parses the same arguments and runs
  the same code as before; the one-line help texts are kept word for word.
- REQ-001-05: The group membership is:
  - setup: `init`, `trust`, `doctor`, `install`
  - specs: `analyze`, `approve`, `worktree`
  - running a spec: `start`, `next`, `halt`, `resume`, `stop`
  - views and status: `status`, `dashboard`, `statusline`, `graph`, `remote`
  - used by the agents during a run: `agent`, `brief`, `check`, `review`, `done`, `assume`,
    `converge`
- REQ-001-06: The usage line, description, `--version` option and epilog (the
  `bash .sdd/bin/sdd <command>` hint and docs link) are still printed.

## Acceptance criteria
- [ ] AC-01: `sdd --help` output contains the five headings in order, and each public
  command's line sits under the heading REQ-001-05 gives it (REQ-001-01, REQ-001-05).
- [ ] AC-02: A test derives the public command set from the parser and checks it equals the
  set of commands in the groups, with no duplicates (REQ-001-02).
- [ ] AC-03: No line of `sdd --help` contains `hook-`; the existing unknown-command test still
  passes (REQ-001-03).
- [ ] AC-04: The existing test suite passes unchanged, and each command's help text in the
  grouped output equals its text before the change (REQ-001-04).
- [ ] AC-05: `--version`, the description and the epilog still appear in `sdd --help`
  (REQ-001-06).

## Risks and open questions
- argparse has no built-in way to group subcommands; the plan renders the groups itself. A
  long command name such as `statusline` must still line up and not wrap oddly.
- The one-line help strings move into a table; a typo while moving them would change user
  text. AC-04 guards that.
- None open; see Clarifications.

## Clarifications
- 2026-11-04: Q: where are the commands only the agents call during a run listed? A: (b) a
  fifth group, "used by the agents during a run", after "views and status", holding `agent`,
  `brief`, `check`, `review`, `done`, `assume` and `converge`; `start`, `next`, `halt`,
  `resume` and `stop` stay in "running a spec". Updated REQ-001-01, REQ-001-05, AC-01, the
  plan and T-001-01, T-001-03.
