# Project constitution

The few rules every spec, plan and change in this project must follow. Keep it short:
briefs carry every line with MUST, MUST NOT or NEVER, and reviewers treat a violation as
CRITICAL. Delete the examples that do not apply and add your own.

## Rules
- Every behaviour change MUST come with a test that fails without it.
- Public functions MUST have type hints and a one-line docstring.
- Code MUST NOT log secrets, tokens or personal data.
- Migrations MUST be reversible.
- NEVER add a dependency without saying why in the plan.

## Notes
Anything here without MUST, MUST NOT or NEVER is guidance for the planner only.
