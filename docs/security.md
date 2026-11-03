# Security model

## What sdd-pilot can do

- Runs the commands in `sdd.toml` (`[[check]]`, `[format]`) from the repository root, **only after you have trusted that exact file** with `sdd trust`.
- Edits files in your project through Claude Code's normal tools and permissions.
- Writes `.sdd/` (git-ignored), merges permission rules into `.claude/settings.json`, and keeps a trust store in `~/.claude/sdd-pilot/trust.json` (or `$SDD_HOME`).
- With `[graphify] auto = true` (the default), installs a pinned version of the `graphifyy` package with `uv tool`, `pipx` or `pip --user`, and builds a local code graph in `graphify-out/`. Set `auto = false` to turn this off.

It never commits, pushes, opens a PR or reads secrets on its own.

## Trust: commands from a cloned repository

A repository can ship any `sdd.toml`, and its commands would run without a prompt (the format hook fires on every edit, and `sdd check` is allow-listed). So sdd-pilot records the sha256 of the `sdd.toml` you trusted, per project, in a store outside the repository. If the file is new or changed, by a clone or by an agent, the gate and the format hook run nothing and tell you to review it and run `sdd trust`, which is an `ask` permission prompt. `sdd init` trusts the file it writes itself, but never one that already existed.

Check commands with a path separator are looked up in the repository; bare names always come from `PATH`.

## Gates

| Gate | How it is enforced |
|---|---|
| Spec approval | `sdd approve` is an `ask` rule. It stores the sha256 of the approved `spec.md` in the trust store. `sdd start` refuses a spec whose status line was edited by hand or whose content changed after approval, and a mid-run change halts the run |
| Trust, start, resume | `ask` rules. Starting again or resuming would reset counters, so the model cannot do it alone; `start` also refuses while a run is active |
| Ticking a task | `sdd done` refuses unless the last passing gate and the last clean review were both recorded for the code as it is now (a fingerprint of the working tree) |
| Gate config | During a run, changing a file listed in `[project] guard` fails `sdd check` until you review it and run `sdd trust`. The reviewer also flags new skip, ignore and threshold changes |
| Run state | A PreToolUse hook denies Edit, Write, MultiEdit and NotebookEdit on `.sdd/` and on the trust store; `init` adds matching deny rules |
| Caps | Failures are recorded against the group in flight by default, and a SubagentStop hook counts subagents, so the agent cap does not depend on the model reporting them |
| Commit, push, PR | `git commit`, `git push`, `gh pr create`, `gh pr merge` are `ask` rules. Over Telegram the prompt is relayed to the paired chat |

`sdd doctor` fails when the `sdd` gate rules are missing or when `defaultMode` is `bypassPermissions`, since prompts do not appear in that mode.

## What is not covered

- The guard hook watches file tools. A shell command writing into `.sdd/` is not parsed, but arbitrary shell commands are not allow-listed, so they prompt.
- The `via` field in `.sdd/approvals.log` is reported by the caller. The permission prompt is the real gate.
- The trust store is a plain file in your home directory. It stops agents working inside the project, not someone with access to your account.
- Review verdicts are reported by the orchestrator from the reviewer's output.

## Telegram

- Pair only your own account and set `/telegram:access policy allowlist`. `sdd remote` warns if there is more than one allowed user, or groups.
- The bot token lives in `~/.claude/channels/telegram/.env`. Do not put it in the repository.
- Messages from the phone are treated as the user's words, but gates move only on the exact commands in the table, and the final decision is the permission prompt.
- The orchestrator is told never to send secrets or `.env` files to the chat. Spec and plan files may be sent; do not use phone control for specs you cannot share with Telegram.
- Anyone who gets control of your Telegram account or bot token can message your session. Use Telegram two-step verification, and revoke the token with BotFather if lost.

## Prompt injection

Specs, plans, repository files and chat messages are inputs a model reads. Every agent prompt says they are data, not instructions, and to report attempts to steer them. The gates above do not depend on the model complying: approvals, trust and resets are permission prompts, and `done` checks recorded results. Review diffs before you approve a commit.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
