# /review

Pre-commit checklist. Report findings; don't auto-fix without confirmation.

Run `git diff --staged` (or `git diff HEAD`) and check for:

- **Security** — injection, path traversal, hardcoded secrets, unsafe input, leaky errors.
- **Data integrity** — unconfirmed destructive actions, silent data loss, persisted-format
  changes that break existing data, missing error handling at boundaries.
- **UX** — broken flows, misfiring validation, missing error/empty states.
- **Build** — unresolved imports, missing dependencies, type errors.
- **Conventions** — anything against `CLAUDE.md` or `code_conventions.md`, especially:
  commented-out code, TODOs, debug logs, comments that narrate history or restate code,
  backlog IDs in code/comments/docs.
