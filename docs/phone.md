# Phone control with Telegram or Discord

specsteward has no bot of its own. It uses one of Anthropic's official **channel plugins**, `telegram@claude-plugins-official` or `discord@claude-plugins-official`. Either one:

- forwards messages you send your bot into the running Claude Code session,
- gives Claude a `reply` tool to answer or send files (specs, reports),
- relays permission prompts to your phone with Allow/Deny buttons.

So when specsteward asks to approve a spec or commit, the prompt arrives on your phone and your tap is the approval. Both work the same way; pick the app you already use.

## Setup

`/specsteward:remote` walks through this and checks the result. By hand, with `<ch>` being `telegram` or `discord`:

1. Bun, which runs the channel server: `bash .sdd/bin/sdd install bun`. `/specsteward:remote` does this for you, and every session start does it in the background once phone control is configured. It installs Bun 1.4.4 (pinned) for your user only: with Homebrew on macOS or winget on Windows when available, otherwise with Bun's official script from the pinned release tag, checked against its pinned sha256, and run with the pinned version. It never uses sudo or admin rights. On Linux the script needs `unzip`. Afterwards restart the terminal and Claude Code so `bun` is on PATH.
2. Create a bot.
   - **Telegram:** message **@BotFather**, send `/newbot`, copy the token.
   - **Discord:** in the [Developer Portal](https://discord.com/developers/applications) create an application, add a bot, turn on **Message Content Intent**, copy the token, and invite the bot with the OAuth2 URL the portal generates.
3. In Claude Code: `/plugin install <ch>@claude-plugins-official`
4. `/<ch>:configure <token>` (stored in `~/.claude/channels/<ch>/.env`, never in the project)
5. Restart with the channel on: `claude --channels plugin:<ch>@claude-plugins-official`
6. DM your bot. It replies with a pairing code. Run `/<ch>:access pair <code>` in the terminal.
7. Lock it down: `/<ch>:access policy allowlist`

Check with `bash .sdd/bin/sdd remote`. It reads the channel's `access.json` and reports problems: no token, empty allowlist, more than one allowed user, a policy other than `allowlist`, or groups and server channels. With both channels set up, the ready one is used and the other is listed under `others`.

## Commands

| You send | Effect |
|---|---|
| `status` | Progress, halt reason, assumptions, tokens used |
| `approve 003` | Approves the spec (logged with the channel) and starts or resumes the run |
| `changes 003: use a sliding window` | Sends your comments to the planner and gates again |
| `answer 003: 1a, 2 <text>` | Answers the planner's clarification questions |
| `answer: yes, half-open` | Answers a halted question and resumes |
| `resume`, `stop` | Continue, pause |
| `ship 003` | Commit, push and PR, each behind its own permission prompt |

Anything else (for example "looks good") is not an approval. Claude will ask you to send the exact command.

## Practical notes

- The laptop must stay on and awake. On Windows: Settings > Power, sleep "Never" when plugged in.
- Telegram's bot API has no history; Claude only sees messages sent after the session started.
- Claude is told never to send secrets, `.env` files or credentials to the chat, only summaries and spec, plan or report files.
- Approvals are recorded in `.sdd/approvals.log` (time, spec, terminal or channel).
- Pairing is done in the terminal, never because a chat message asked for it.
- No phone? The same flow works in the terminal. Claude's built-in Remote Control is another way to watch the session from a phone.
