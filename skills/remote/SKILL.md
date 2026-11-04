---
name: remote
description: Set up phone control for specsteward through the official Telegram channel plugin and check that it is safe (token, pairing, allowlist policy). Use for "/specsteward:remote" or when the user wants to approve specs or runs from their phone.
---

# specsteward remote (Telegram)

specsteward does not run its own bot. It uses the official Telegram channel plugin, which
forwards your Telegram messages into this Claude Code session and relays permission
prompts to your phone with Allow/Deny buttons.

1. Run `bash .sdd/bin/sdd remote` and read `problems`.
2. Walk the user through whatever is missing, one step at a time:
   1. **Bun** (the channel server runs on it): run `bash .sdd/bin/sdd install bun`. It
      installs the pinned version for this user (Homebrew or winget when available,
      else Bun's official script; no admin rights). Do this without asking, and tell
      the user in one line what was installed. If it fails, show the fix it prints.
   2. Create a bot: in Telegram, message @BotFather, send `/newbot`, copy the token.
   3. `/plugin install telegram@claude-plugins-official`
   4. `/telegram:configure <token>` (stored in `~/.claude/channels/telegram/.env`, not in
      the project).
   5. Restart Claude Code with the channel on:
      `claude --channels plugin:telegram@claude-plugins-official`
   6. DM the bot; it replies with a pairing code. Run `/telegram:access pair <code>`.
   7. Lock it down: `/telegram:access policy allowlist`.
3. Run `bash .sdd/bin/sdd remote` again. When `ready` is true, send a test message with
   the Telegram `reply` tool to the first chat ID: "specsteward connected. Commands: status,
   approve <NNN>, changes <NNN>: ..., answer: ..., resume, ship <NNN>, stop."
4. Remind the user:
   - The laptop must stay on and awake while a run is going (on Windows: Power settings,
     sleep "Never" when plugged in).
   - Approvals, commits, pushes and PRs still need their tap on the permission prompt.
   - Anyone who can DM the bot cannot do anything unless they are on the allowlist, which
     should contain only the user.
