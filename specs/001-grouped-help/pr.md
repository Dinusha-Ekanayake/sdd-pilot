# Grouped `sdd --help` (spec 001)

## Summary

`sdd --help` now lists the public commands under five headings instead of one flat list:
setup, specs, running a spec, views and status, and used by the agents during a run. The
headings and the one-line help of every command come from a single `COMMAND_GROUPS` table in
`specsteward/__main__.py`, and a test fails if a command is added to the parser without a group
(or a group names a command that does not exist). The change is display-only: no command's
arguments, behaviour, exit codes or per-command help changed, and the internal hook commands
stay out of the help.

## Changes

- `specsteward/__main__.py`:
  - `COMMAND_GROUPS` holds the five groups, with each command's existing help text verbatim.
  - `_parser()` takes each subcommand's `help` from the table.
  - `_grouped_commands()` renders the grouped block; `_Parser.format_help()` swaps argparse's
    flat list for it on the top-level parser only.
  - The usage line is set explicitly (`sdd [-h] [--version] <command> ...`) so it stays intact in
    narrow terminals. The description, `--version`, options and epilog are still printed.
- `tests/test_help.py` (new): frozen help texts, group membership, completeness against the
  parser (including a failing case for an ungrouped and a missing command), heading order,
  hidden hooks, the narrow-terminal usage line, and per-command options.
- `specs/001-grouped-help/`: the approved spec, plan and task table.
- `CHANGELOG.md`: one entry under 0.2.0, Added.

Also on this branch (not part of spec 001, committed earlier as `b5132ad`):

- `fix: re-running init keeps the user's relaxed git rules`: on a re-run, `sdd init` adds only
  the sdd gates and deny rules, not the git ask rules the user removed; `sdd doctor` names the
  missing deny rules. Touches `specsteward/init.py`, `specsteward/doctor.py`,
  `tests/test_doctor.py`, `tests/test_hooks_init_cli.py`, `.claude/settings.json`,
  `specs/_template_fix/` and `specs/constitution.md`.

Diff against `main` (`git diff main --stat`): 10 files, 212 insertions, 31 deletions. Spec 001's
own change is `specsteward/__main__.py` (+106 / -28 against HEAD), plus `tests/test_help.py`,
`specs/001-grouped-help/` and `CHANGELOG.md`.

## Test plan

- [ ] `pytest tests/test_help.py` passes
- [ ] Full test suite passes unchanged (`pytest`), including `test_unknown_command_does_not_list_internal_hooks`
- [ ] `sdd --help` shows the five headings in order, each command under the heading in the spec (REQ-001-05)
- [ ] No `hook-*` line in `sdd --help`; unknown-command error unchanged
- [ ] `sdd --help` and `sdd -h` look right at a narrow terminal width (usage line not broken)
- [ ] `sdd init --help` and `sdd approve --help` unchanged apart from the usage prefix
- [ ] Manual check in a real terminal on Windows Git Bash and one Unix shell: alignment and readability (task T-001-05, human sign-off; paste the output here)
- [ ] `sdd check` gate passes on this branch

https://claude.ai/code/session_01RB6Ugij6hby1iQNRkEwk1E
