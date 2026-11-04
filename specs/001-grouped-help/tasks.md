# Tasks 001: Grouped `sdd --help`

Risk decides the reviewer and the gate:
- `high`: correctness-critical (data leakage, security, money, migrations, metrics, determinism). Opus review plus one adversarial test.
- `low`: helpers, config, wiring. Sonnet review.
- `human`: runs on real data or systems, interpretation, release, close-out. Prepared automatically, signed off by you.

Status: `[ ]` open, `[x]` done, `[?]` prepared and waiting for your sign-off.

| ID | Task | Test | Risk | Status |
|---|---|---|---|---|
| T-001-01 | Add `COMMAND_GROUPS` in `specsteward/__main__.py` with the five groups and the existing help texts verbatim; `_parser` takes each command's `help` from it (REQ-001-04, REQ-001-05) | `tests/test_help.py`: a frozen dict of the 24 pre-change help texts equals the texts in `COMMAND_GROUPS`; each command's group matches REQ-001-05 | low | [x] |
| T-001-02 | Completeness guard: public subcommands of `_parser()` minus `HOOKS` equal the names in `COMMAND_GROUPS`, no duplicates, no `hook-*` in any group (REQ-001-02, REQ-001-03) | `tests/test_help.py`: the set test fails when a fake extra subparser is added without a group, and when a group names a missing command | low | [x] |
| T-001-03 | Render the grouped block with `_grouped_commands()` and suppress argparse's flat list, keeping usage, description, options, `--version` and epilog (REQ-001-01, REQ-001-03, REQ-001-06) | `tests/test_help.py`: `main(["--help"])` shows the five headings in order, each command under its heading, no line containing `hook-`, no flat command list, epilog and `--version` present | low | [x] |
| T-001-04 | Behaviour unchanged: per-command help and parsing are as before (REQ-001-04) | `tests/test_help.py`: `sdd init --help` and `sdd approve --help` still list their options; the existing suite, including `test_unknown_command_does_not_list_internal_hooks`, passes via `sdd check` | low | [x] |
| T-001-05 | Read the new `bash .sdd/bin/sdd --help` in a real terminal (Windows Git Bash and one Unix shell), confirm alignment and that the groups help a new user, then sign off (REQ-001-01) | manual: output pasted into the PR description | human | [?] |
