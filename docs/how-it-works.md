# How it works

## Pieces

| Piece | Role |
|---|---|
| `agents/planner.md` (Opus) | Drafts spec, plan, tasks. Never approves |
| `agents/implementer.md` (Sonnet) | TDD for one task group from a brief; reused across groups, restarted every few tasks |
| `agents/reviewer.md` (Sonnet or Opus) | Reviews the diff against the brief; Opus plus an adversarial test on high-risk tasks |
| `agents/clerk.md` (Haiku) | Changelog, dev log and PR draft |
| `skills/run` | The orchestration loop and the phone command table |
| `skills/init`, `skills/remote` | Setup helpers |
| `sdd_pilot/` | The deterministic part, as a standard-library Python CLI |
| `hooks/hooks.json` | SessionStart (shim and context), PostToolUse (format), Stop (continue) |

Everything that can be a script is a script, so models spend tokens only on judgement: the CLI parses tasks, builds briefs, runs the gate, counts failures and enforces caps.

## The loop

```
sdd start 003            refuses unless spec approved and branch matches
loop:
  sdd next               -> {tasks, risk, reviewer_model, restart_implementer} | halted | done
  sdd brief T-003-01 ... -> .sdd/briefs/T-003-01.md
  implementer(brief)     -> short report
  sdd check --task ...   -> PASS | FAIL + signature (same signature twice halts)
  reviewer(brief)        -> VERDICT clean|changes (second open round halts)
  sdd done T-003-01 ...  -> ticks tasks.md ([?] for human tasks)
done: clerk, final Opus review of the branch, wait for "ship"
```

## Stop hook

While a run is active and tasks are open, the Stop hook asks Claude to continue, but only if a task was completed since the last automatic continue. No progress halts the run. A halted or stopped run never blocks a stop.

## State

`.sdd/state.json` (git-ignored) holds the run: spec, halt reason, agent-run count, per-task failures, review rounds and assumptions. `.sdd/briefs/` holds briefs, `.sdd/approvals.log` the approvals, `.sdd/bin/sdd` a stable shim to the installed plugin version so permission rules do not change across plugin updates.

## Briefs

A brief contains the task rows; the lines of `plan.md` that mention the same backticked paths or identifiers (plain words are ignored so unrelated rows do not match); the `REQ-` and `AC-` lines of the spec; signatures of the files the plan names, plus the siblings of any new file so the implementer reuses what exists; optional graphify nodes; and the rules and report format.

## Design choices

- **No custom bot.** The official channel plugin already handles pairing, allowlists and permission relay.
- **Standard library only.** Nothing to install; Python 3.11+ is the only requirement.
- **Gates are permission prompts**, not chat text, so they cannot be satisfied by a model reading a message.
- **Hooks no-op without `sdd.toml`,** so a global install is safe.
