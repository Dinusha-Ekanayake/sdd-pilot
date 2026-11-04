# specsteward constitution

Rules every spec, plan and change to specsteward itself must follow. Briefs carry every line
with MUST, MUST NOT or NEVER, and reviewers treat a violation as CRITICAL.

## Rules
- Runtime code MUST use the Python standard library only; dev tools go in `[project.optional-dependencies]`.
- Every behaviour change MUST come with a test that fails without it; a fix starts with a regression test.
- A gate MUST NOT be weakened (an ask rule removed, a check skipped, a cap loosened) without a test proving what it still guarantees.
- Anything a cloned repository or an agent controls MUST NOT run, install or be written to before the user trusts or approves it.
- Hooks MUST NOT break the user's session: errors go to stderr and the hook exits 0.
- Every error or halt message a user can see MUST say what to do next, and halts MUST be explained in `docs/faq.md`.
- Security-relevant changes MUST update `docs/security.md`, including what is still not covered.
- NEVER add telemetry or send data anywhere the user did not set up.
- NEVER add AI or assistant attribution to commits, pull requests or release notes.

## Notes
Prefer small modules (under 400 lines) and plain wording in user-facing text.
