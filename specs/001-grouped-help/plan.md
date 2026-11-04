# Plan 001: Grouped `sdd --help`

## Approach
argparse prints subcommands as one flat list and has no subcommand groups. Keep argparse
for parsing and change only what the top-level help prints:

1. Add a module-level table `COMMAND_GROUPS` in `specsteward/__main__.py`: a tuple of
   `(heading, ((name, help), ...))` pairs for the five groups, in display order, holding the existing one-line
   help texts word for word (REQ-001-04, REQ-001-05).
2. In `_parser`, keep every `sub.add_parser(...)` call and its arguments as they are, but
   take each command's `help` text from `COMMAND_GROUPS` (a small `_help(name)` lookup), so
   per-command help and parsing are unchanged.
3. Stop argparse printing its own flat list by passing `help=argparse.SUPPRESS` to
   `add_subparsers`, and render the groups in a helper `_grouped_commands()` that returns
   the text block (a heading line, then each command padded to the longest name). The block
   goes into the top-level parser's `description` with
   `formatter_class=argparse.RawDescriptionHelpFormatter`, so its line breaks survive
   (REQ-001-01, REQ-001-06). The usage line keeps `<command>`.
4. `HOOKS` commands are still registered with no help and are not in `COMMAND_GROUPS`, so
   they never reach the rendered block (REQ-001-03). `_Parser.error` stays as it is.

The implementer may choose an override of `_Parser.format_help` instead of the description
trick if that is simpler, as long as the tests below pass; the table stays the single
source of command names, groups and help texts.

## Modules / files
| File | Responsibility |
|---|---|
| `specsteward/__main__.py` | `COMMAND_GROUPS` table, `_grouped_commands()` renderer, `_parser` reads help texts from the table and suppresses the flat list |
| `tests/test_help.py` | grouped-output tests: heading order, membership, completeness against the parser, no `hook-` lines, help texts unchanged, epilog and `--version` kept |

## Data flow
`main(["--help"])` -> `_parser()` builds the parser; help texts come from `COMMAND_GROUPS`
-> argparse prints usage, the description plus the grouped block from
`_grouped_commands()`, options and epilog -> exit 0. Every other argv goes through the same
subparsers as today.

## Test strategy
- Capture `main(["--help"])` output with `capsys` (it raises `SystemExit(0)`).
- Assert the five headings appear in order and each command line falls between its
  heading and the next one (REQ-001-01, REQ-001-05).
- Read the subparser choices from `_parser()` (the `_SubParsersAction`), drop `HOOKS`, and
  assert the set equals the names in `COMMAND_GROUPS` with no duplicates (REQ-001-02).
- Assert no output line contains `hook-` (REQ-001-03).
- Keep a frozen dict of the 24 help texts as they are before the change and assert each
  appears verbatim in the grouped output; `sdd init --help` and `sdd approve --help` still
  list their options (REQ-001-04).
- Assert the description, epilog and `--version` are present (REQ-001-06).
- The full existing suite runs through the gate (`sdd check`) unchanged.

## Risks
- Suppressing argparse's list but leaving an empty "positional arguments" section; the
  test asserts that heading is absent or not followed by a flat command list.
- Column padding for `statusline`/`dashboard`: render with the longest name's width so no
  line wraps; covered by the membership test reading one command per line.
- Python version differences in argparse output (3.10 uses "options:", older "optional
  arguments:"): tests must not depend on that heading.
