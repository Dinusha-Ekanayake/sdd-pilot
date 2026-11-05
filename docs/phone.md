# Phone control with Telegram or Discord

specsteward has no bot of its own. It uses one of Anthropic's official **channel plugins**, `telegram@claude-plugins-official` or `discord@claude-plugins-official`. Either one:

- forwards messages you send your bot into the running Claude Code session,
- gives Claude a `reply` tool to answer or send files (specs, reports),
- relays permission prompts to your phone with Allow/Deny buttons.

So when specsteward asks to approve a spec or commit, the prompt arrives on your phone and your tap is the approval. Both work the same way; pick the app you already use.

## Setup

Run `/specsteward:remote` in Claude Code, or `bash .sdd/bin/sdd phone setup` (add `--channel discord` for Discord). In one step it:

- installs Bun, which runs the channel server (pinned version 1.4.4, for your user only, checksum-verified; on Linux it needs `unzip`);
- installs the official plugin (`telegram@claude-plugins-official` or `discord@claude-plugins-official`);
- switches the plugin **off in ordinary sessions**, so other terminals and VS Code panels no longer start their own copy of the bot and swallow your replies;
- installs a **`claude-phone`** command (next to `claude`; `claude-phone.cmd` too on Windows) that starts Claude Code with the plugin loaded and its channel on.

Then, once:

1. Create a bot.
   - **Telegram:** message **@BotFather**, send `/newbot`, copy the token.
   - **Discord:** in the [Developer Portal](https://discord.com/developers/applications) create an application, add a bot, turn on **Message Content Intent**, copy the token, and invite the bot with the OAuth2 URL the portal generates.
2. Exit Claude Code and start it with **`claude-phone`** instead of `claude`.
3. In that session: `/<ch>:configure <token>` (stored in `~/.claude/channels/<ch>/.env`, never in the project).
4. DM your bot. It replies with a pairing code. Run `/<ch>:access pair <code>` in the terminal.
5. `bash .sdd/bin/sdd phone lock` so only your account can use the bot.

From then on, start Claude Code with `claude-phone` whenever you want phone control; any arguments are passed on (`claude-phone --resume`).

Check with `bash .sdd/bin/sdd remote`. It reports problems: no token, empty allowlist, more than one allowed user, a policy other than `allowlist`, or groups and server channels. `bash .sdd/bin/sdd doctor` also warns when the plugin is on in every session or several bots are running.

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
