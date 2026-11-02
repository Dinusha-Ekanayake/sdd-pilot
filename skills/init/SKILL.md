---
name: init
description: Set up sdd-pilot in the current repository - sdd.toml from a preset (python, node, generic), spec/plan/tasks templates, .gitignore entry and permission rules (approvals, commit, push and PR stay behind "ask"). Use for "/sdd-pilot:init".
---

# sdd-pilot init

1. Detect the stack: `pyproject.toml` or `setup.py` → `python`; `package.json` → `node`;
   otherwise `generic`. Ask the user only if it is ambiguous.
2. Run the launcher from the plugin (its path is in this skill's base directory, two
   levels up: `<base>/../../bin/sdd`):
   `bash "<plugin root>/bin/sdd" init --preset <preset>`
   It creates `sdd.toml`, `specs/_template/`, `.sdd/bin/sdd` (the stable entry point),
   the `.gitignore` entry, and permission rules in `.claude/settings.json`. It never
   overwrites existing files without `--force`.
3. Open `sdd.toml` and adjust the `[[check]]` commands to the project's real lint, type
   and test commands. Run `bash .sdd/bin/sdd check` once; it must work before any run.
4. If the project has hard rules on wording (for example safety or legal claims), add
   them as regexes under `[wording] banned`.
5. Tell the user what was created and the next steps:
   - `/sdd-pilot:run plan <topic>` to draft a spec, or write one from the template.
   - `/sdd-pilot:remote` to approve gates from a phone.
   - Restart Claude Code once so the new permission rules load.
