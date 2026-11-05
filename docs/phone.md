# Phone control with Telegram or Discord

specsteward has no bot of its own. It uses one of Anthropic's official **channel plugins**, `telegram@claude-plugins-official` or `discord@claude-plugins-official`. Either one:

- forwards messages you send your bot into the running Claude Code session,
- gives Claude a `reply` tool to answer or send files (specs, reports),
- relays permission prompts to your phone with Allow/Deny buttons.

So when specsteward asks to approve a spec or commit, the prompt arrives on your phone and your tap is the approval. Both work the same way; pick the app you already use.

## Setup

In a terminal of your own (not inside Claude Code), in your project:

```bash
bash .sdd/bin/sdd phone setup            # add --channel discord for Discord
```

It does everything it can by itself, and walks you through the rest:

- installs Bun, which runs the channel server (pinned version 1.4.4, for your user only, checksum-verified; on Linux it needs `unzip`);
- installs the official plugin (`telegram@claude-plugins-official` or `discord@claude-plugins-official`);
- switches the plugin **off in ordinary sessions**, so other terminals and VS Code panels no longer start their own copy of the bot and swallow your replies;
- installs a **`claude-phone`** command (next to `claude`; `claude-phone.cmd` too on Windows) that starts Claude Code with the plugin loaded and its channel on;
- tells you how to create the bot (Telegram: [@BotFather](https://t.me/BotFather), `/newbot`), asks you to paste the token at a hidden prompt, checks it with the bot API and saves it to `~/.claude/channels/<ch>/.env` (never in the project);
- **Telegram:** asks you to send the bot any message, shows who wrote ("Message from @you, account 123. Is this you?"), and on your `y` allows only that account and locks the bot. You confirm on your own keyboard, so a message from someone else can never pair itself. It then sends a test message to your phone;
- **Discord:** pairing goes through the plugin: in the `claude-phone` session DM the bot, run `/discord:access pair <code>`, then `bash .sdd/bin/sdd phone lock --channel discord`;
- offers to start `claude-phone` right away.

So for Telegram you do four things: create the bot, paste the token, send one message, press `y`. Run it again at any time: it keeps a working token and lock, and only asks again for what is missing.

`/specsteward:remote` in Claude Code runs the automatic part and tells you to open a terminal for the rest (Claude Code's own shell cannot take a hidden token). `--no-input` does the same from a script. The by-hand route still works: in a `claude-phone` session run `/<ch>:configure <token>`, DM the bot, `/<ch>:access pair <code>`, then `bash .sdd/bin/sdd phone lock`.

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
