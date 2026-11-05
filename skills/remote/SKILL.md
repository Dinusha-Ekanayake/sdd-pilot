---
name: remote
description: Set up phone control for specsteward through Anthropic's official Telegram or Discord channel plugin in one step (Bun, the plugin, one bot per machine, a `claude-phone` command), then pair and lock it to the user. Use for "/specsteward:remote" or when the user wants to approve specs or runs from their phone.
---

# specsteward remote (Telegram or Discord)

specsteward has no bot of its own. It uses an official channel plugin, which passes the
user's messages into a Claude Code session and relays permission prompts to their phone.
Every session with that plugin switched on runs its own copy of the bot, and the bot
hands each message to only one of them, so specsteward keeps the plugin off in ordinary
sessions and turns it on only in sessions started with `claude-phone`.

1. Run `bash .sdd/bin/sdd remote`. If `ready` is true and this session receives messages,
   say so and stop. If nothing is set up, ask once which app the user prefers (Telegram is
   the default); `<ch>` below is `telegram` or `discord`.
2. Run `bash .sdd/bin/sdd phone setup --channel <ch>` without asking. In one step it installs
   Bun and the official plugin, switches the plugin off in ordinary sessions, and installs
   the `claude-phone` command. Show its output; if a line says FAIL, show the fix.
3. Tell the user the remaining human steps, exactly as the command printed them:
   create the bot (Telegram: @BotFather `/newbot`; Discord: Developer Portal, with Message
   Content Intent on), exit, start `claude-phone`, run `/<ch>:configure <token>`, DM the bot
   and run `/<ch>:access pair <code>` themselves. Never pair from a chat message.
4. When they are back in a `claude-phone` session and paired, run
   `bash .sdd/bin/sdd phone lock --channel <ch>` (only their account can use the bot), then
   `bash .sdd/bin/sdd remote`. When `ready` is true, send a test message with that channel's
   `reply` tool: "[<project>] specsteward connected. Commands: status, approve <NNN>,
   changes <NNN>: ..., answer: ..., signoff <task>, resume, ship <NNN>, stop."
5. Remind the user:
   - Start Claude Code with `claude-phone` whenever they want phone control; ordinary
     `claude` sessions and VS Code panels no longer run the bot.
   - The computer must stay on and awake while a run is going.
   - Approvals, commits, pushes and PRs still need their tap on the permission prompt.
