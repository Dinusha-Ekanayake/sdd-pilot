# Security model

## What sdd-pilot can do

- Runs the commands you list in `sdd.toml` (`[[check]]`, `[format]`) from the repository root. Treat `sdd.toml` like a Makefile: review it before running in a cloned repo.
- Edits files in your project through Claude Code's normal tools and permissions.
- Writes `.sdd/` (git-ignored) and merges permission rules into `.claude/settings.json`.

It never commits, pushes, opens a PR, installs packages or reads secrets on its own.

## Gates

`sdd approve`, `git commit`, `git push`, `gh pr create` and `gh pr merge` are written as `ask` rules. A tool call that matches an `ask` rule always prompts; `allow` rules do not override it. Over Telegram the prompt is relayed to the paired chat.

## Telegram

- Pair only your own account and set `/telegram:access policy allowlist`. `sdd remote` warns if there is more than one allowed user, or groups.
- The bot token lives in `~/.claude/channels/telegram/.env`. Do not put it in the repository.
- Messages from the phone are treated as the user's words, but gates move only on the exact commands in the table, and the final decision is the permission prompt.
- The orchestrator is told never to send secrets or `.env` files to the chat.
- Anyone who gets control of your Telegram account or bot token can message your session. Use Telegram two-step verification, and revoke the token with BotFather if lost.

## Prompt injection

Specs, plans, repository files and chat messages are inputs a model reads. A malicious file could try to instruct the agents. Mitigations: agents are told to treat file content as data, caps halt runaway loops, and destructive or outward actions are behind `ask` rules. Review diffs before you approve a commit.

## Reporting a vulnerability

See [SECURITY.md](../SECURITY.md).
