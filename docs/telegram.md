# Phone control with Telegram

sdd-pilot has no bot of its own. It uses Anthropic's official **Telegram channel plugin** (`telegram@claude-plugins-official`), which:

- forwards messages you send your bot into the running Claude Code session,
- gives Claude a `reply` tool to answer or send files (specs, reports),
- relays permission prompts to your phone with Allow/Deny buttons.

So when sdd-pilot asks to approve a spec or commit, the prompt arrives on your phone and your tap is the approval.

## Setup

`/sdd-pilot:remote` walks through this and checks the result. By hand:

1. Install [Bun](https://bun.sh). The channel server runs on it.
2. In Telegram, message **@BotFather**, send `/newbot`, copy the token.
3. In Claude Code: `/plugin install telegram@claude-plugins-official`
4. `/telegram:configure <token>` (stored in `~/.claude/channels/telegram/.env`, never in the project)
5. Restart with the channel on: `claude --channels plugin:telegram@claude-plugins-official`
6. DM your bot. It replies with a pairing code. Run `/telegram:access pair <code>`.
7. Lock it down: `/telegram:access policy allowlist`

Check with `bash .sdd/bin/sdd remote`. It reads the channel's `access.json` and reports problems: no token, empty allowlist, more than one allowed user, a policy other than `allowlist`, or groups.

## Commands

| You send | Effect |
|---|---|
| `status` | Progress, halt reason, assumptions |
| `approve 003` | Approves the spec (logged with `via telegram`) and starts the run |
| `changes 003: use a sliding window` | Sends your comments to the planner and gates again |
| `answer: yes, half-open` | Answers a halted question and resumes |
| `resume`, `stop` | Continue, pause |
| `ship 003` | Commit, push and PR, each behind its own permission prompt |

Anything else (for example "looks good") is not an approval. Claude will ask you to send the exact command.

## Practical notes

- The laptop must stay on and awake. On Windows: Settings > Power, sleep "Never" when plugged in.
- Telegram's bot API has no history. Claude only sees messages sent after the session started.
- Claude is told never to send secrets, `.env` files or credentials to the chat, only summaries and spec, plan or report files.
- Approvals are recorded in `.sdd/approvals.log` (time, spec, terminal or telegram).
- No Telegram? The same flow works in the terminal. A second option is Claude's built-in Remote Control for a phone view of the session.
