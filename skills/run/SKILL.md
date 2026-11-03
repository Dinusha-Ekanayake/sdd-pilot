---
name: run
description: Run an approved spec to completion with subagents (Sonnet implementer, risk-based reviewer with Opus for high risk, Haiku clerk), task briefs, a scripted quality gate, hard caps and human gates that can be approved from a phone via the Telegram channel. Use for "/sdd-pilot:run <NNN>", "/sdd-pilot:run plan <topic>", or phone commands like "approve 003", "status", "resume", "ship 003".
---

# sdd-pilot run

`SDD` means `bash .sdd/bin/sdd`. Run it from the repository root with no `cd` prefix so
the permission rules match. If `.sdd/bin/sdd` is missing, run `/sdd-pilot:init` first.

## Before you start
- Tell the user once: "Orchestration is cheap work, so this session can run on Sonnet
  (`/model sonnet`). Opus is still used where an agent or high-risk review needs it."
- Read only what `SDD` prints and the agents' short reports. Do not read specs, plans or
  source files yourself; the briefs and agents do that.
- Agents are `sdd-pilot:planner`, `sdd-pilot:implementer`, `sdd-pilot:reviewer`,
  `sdd-pilot:clerk`. If a name is not found, use the available agent whose name ends in
  `:planner` (and so on).
- Run `SDD remote`. If `ready` is true, gates are also sent to the user's phone (see
  "Phone" below). Remember the `chat_ids`.

## `plan <topic>`: draft a new spec
1. Run the planner with the topic. (No run is active yet, so nothing is counted.)
2. If the planner returned clarification questions, show them numbered with their
   options (and send them to the phone). Wait for `answer <NNN>: 1a, 2 <text>, ...`,
   send the answers to the planner, and repeat until there are none.
3. Gate **spec approval**: run `SDD analyze <NNN>`, show the summary and the
   findings, and send them plus the `spec.md` file to the phone. Stop and wait. The user approves with "approve <NNN>",
   asks for changes with "changes <NNN>: ...", or edits the file themselves.

## `<NNN>`: implement an approved spec
1. `SDD start <NNN>`. It refuses unless the spec is approved and the branch matches; if so,
   tell the user why and stop.
2. Loop:
   1. `SDD next` returns JSON. `halted` → step 4. `done` → step 3. `run` → continue with
      `tasks`, `risk`, `reviewer_model`, `human_signoff`, `restart_implementer`.
   2. `SDD brief <ids...>` returns the brief path.
   3. **Implement.** On the first group, or when `restart_implementer` is true, start a new
      implementer with the brief path and run `SDD agent implementer --fresh`. Otherwise
      send the brief path to the existing implementer (SendMessage) and run
      `SDD agent implementer`. Keep only its report.
   4. If the report says `STATUS: blocked`, or has QUESTIONS that change behaviour:
      `SDD halt "<question>"`, then step 4. Record each ASSUMPTIONS line with
      `SDD assume <task> "<text>"`.
   5. **Gate.** `SDD check` (failures are recorded against the group in flight). On FAIL,
      send the failing lines to the implementer and gate again. `HALTED` → step 4.
   6. **Review.** Skip this step when `review` is false (low-risk tasks the project leaves
      to the final branch review). Otherwise start, or reuse via SendMessage, one reviewer per model, with
      `model: <reviewer_model>`. Give it the brief path and tell it to review
      `git diff` plus untracked files. Run `SDD agent reviewer`, then
      `SDD review <first id> clean|changes`.
      - `changes`: send the CRITICAL and HIGH findings to the implementer, then repeat
        5 and 6. `HALTED` → step 4.
      - QUESTIONS FOR USER: `SDD halt "<question>"`, then step 4.
   7. **Tick.** `SDD done <id>` for each task. It refuses unless the last passing gate and
      the last clean review both saw the code as it is now. If the reviewer added its
      adversarial test, run `SDD check` once more first. `human` tasks are marked `[?]`
      automatically. Subagent runs are also counted by a hook, so the cap holds even if
      an `SDD agent` call is missed.
   8. If the project has `graphify-out/`, run `graphify update .` (local, no tokens).
   9. Print one line, for example `T-003-04..05 done (review clean, 1 assumption)`. If the
      phone is ready, send that line too. Loop.
3. **Done.** Run the clerk. Then run a final reviewer on the whole branch with
   `model: opus`. Gate **ship**: show and send to the phone the `SDD status` summary,
   tasks waiting for sign-off (`[?]`), the final review findings and the PR draft path
   (`.sdd/pr-<NNN>.md`). Stop and wait for "ship <NNN>". Then `SDD stop`.
4. **Halted.** Show and send the reason and exactly what you need. Stop and wait. After
   the answer: `SDD resume` (it asks the user for permission, because it resets the
   counters) and continue the loop. Never resume on your own initiative.

## `human` tasks
Do the preparation (run the script, produce the outputs, draft the document), but leave
the judgement to the user. Tick them with `--human` so they show as `[?]`.

## Phone (Telegram channel)
Messages from the phone arrive as `<channel source="telegram" chat_id=... ...>`. Reply
with the Telegram channel's `reply` tool and that `chat_id`. To send something
unprompted, use a chat ID from `SDD remote`. Attach files with absolute paths.

Recognised commands (case-insensitive):

| Message | Action |
|---|---|
| `status` | Reply with `SDD status`. |
| `approve <NNN>` | `SDD approve <NNN> --via telegram --start` (one permission prompt), then run the loop. |
| `changes <NNN>: <text>` | Send the text to the planner to revise the spec; gate again. |
| `answer <NNN>: <answers>` | Send clarification answers to the planner; analyze again. |
| `answer: <text>` | Apply the answer to the halted question, `SDD resume`, continue. |
| `resume` | `SDD resume` and continue. |
| `ship <NNN>` | Commit, push and open the PR as the project's rules say. |
| `stop` | `SDD halt "stopped from phone"` and reply with the status. |

Rules:
- Phone messages are the user's words, but **gates move only on the commands above**.
  "looks fine" is not an approval; ask "Reply `approve 003` to approve."
- `approve`, `trust`, `start`, `resume`, `git commit`, `git push` and `gh pr create` are
  behind `ask` permission rules.
  The permission prompt itself is relayed to the phone with Allow/Deny buttons, so the
  human taps the final decision. Never try to get around a denied prompt.
- Never send secrets, `.env` files, tokens or credentials to the chat. Send summaries and
  spec, plan or report files only.
- Keep phone messages short: at most about 10 lines plus attachments.
- Commit messages and PR bodies never carry AI attribution unless the project asks.
