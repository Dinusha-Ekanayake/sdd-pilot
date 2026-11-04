---
name: remote
description: Set up phone control for specsteward through Anthropic's official Telegram or Discord channel plugin and check that it is safe (Bun, token, pairing, allowlist policy). Use for "/specsteward:remote" or when the user wants to approve specs or runs from their phone.
---

# specsteward remote (Telegram or Discord)

specsteward does not run its own bot. It uses an official channel plugin, which forwards
the user's messages into this Claude Code session and relays permission prompts to their
phone with Allow/Deny buttons. Telegram and Discord work the same way; `<ch>` below is
`telegram` or `discord`.

1. Run `bash .sdd/bin/sdd remote` and read `channel`, `ready`, `problems` and `others`.
   If nothing is set up yet, ask once which app the user prefers (Telegram is the default).
2. Walk the user through whatever is missing, one step at a time:
   1. **Bun** (the channel server runs on it): run `bash .sdd/bin/sdd install bun`. It
      installs the pinned version for this user (Homebrew or winget when available,
      else Bun's checksum-verified official script; no admin rights). Do this without
      asking, and tell the user in one line what was installed. If it fails, show the fix.
   2. Create a bot.
      - Telegram: message @BotFather, send `/newbot`, copy the token.
      - Discord: in the Developer Portal create an application, add a bot, enable
        **Message Content Intent**, copy the token, and invite the bot with the URL the
        portal generates.
   3. `/plugin install <ch>@claude-plugins-official`
   4. `/<ch>:configure <token>` (stored in `~/.claude/channels/<ch>/.env`, not in the
      project).
   5. Restart Claude Code with the channel on:
      `claude --channels plugin:<ch>@claude-plugins-official`
   6. DM the bot; it replies with a pairing code. The user runs `/<ch>:access pair <code>`
      in the terminal themselves.
   7. Lock it down: `/<ch>:access policy allowlist`.
3. Run `bash .sdd/bin/sdd remote` again. When `ready` is true, send a test message with
   that channel's `reply` tool to the first chat ID: "specsteward connected. Commands:
   status, approve <NNN>, changes <NNN>: ..., answer: ..., resume, ship <NNN>, stop."
4. Remind the user:
   - The laptop must stay on and awake while a run is going (on Windows: Power settings,
     sleep "Never" when plugged in).
   - Approvals, commits, pushes and PRs still need their tap on the permission prompt.
   - Anyone who can DM the bot cannot do anything unless they are on the allowlist, which
     should contain only the user. Pairing approvals are never done from a chat message.
