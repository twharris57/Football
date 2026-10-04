# Code Conventions

Universal rules. Language files add to these rather than repeat them.

## Writing: comments, docstrings, docs

Concise and readable beats complete. Code should read on its own.

- **Comments explain *why*, only when it's surprising** — a hidden constraint, an
  external quirk, a non-obvious invariant. Never restate what the code does.
- **A comment describing a runtime event belongs in a log message.** If it doesn't
  work as a log line and isn't truly unusual, delete it or move it to `docs/`.
- **Docstrings: one line by default.** Add `Args`/`Returns` only when they aren't obvious
  from names and types. No history, no rationale essays, no links to other docs.
- **No history anywhere but git.** Not "fixed after X", "originally Y", "found in review".
  Commit messages and PRs are the record.
- **No backlog IDs (`CP-3`, `SC-18`, `#123`) in code, comments, or docs.** They're
  deleted when done and leave dangling pointers. Name the feature instead.
- **Docs describe current behavior and long-lived decisions only.** Structure for
  skimming, say each fact once, write for the reader. Small mermaid diagrams where a
  picture beats prose.

## Security

- Never commit secrets — use env vars or a secrets store. If one leaks, rotate it;
  scrubbing history isn't enough.
- Never log secrets, PII, or user-entered values. Log opaque IDs.

## Hygiene

- No commented-out code, `TODO`/`FIXME`, or debug logging in committed code.
- Scripts end with an explicit `OK: ...` / `FAIL: ...` and matching exit code. Don't
  swallow error output for quieter logs (`curl -sS`, not `curl -s`).
- Script output and log messages stay ASCII, or the stream is explicitly UTF-8 —
  Windows consoles default to cp1252 and raise `UnicodeEncodeError` on emoji/arrows.

## Design

- **Simplest correct solution.** No abstraction until three real cases; no hypothetical
  requirements; no stubs or placeholder logic.
- **Follow existing patterns** before inventing a second way to do something.
- **One implementation per question.** If two features ask the same thing, reuse or
  extend the existing function — two algorithms will drift and disagree.
- **Fix the model, not the symptom.** A second guard for the same failure means the
  data model is wrong.
- **Senior engineer test:** would they call it overcomplicated? Then simplify.

## Correctness lessons

Patterns that have caused real bugs here.

- **Silent degradation must be visible.** A fallback, empty join, or skipped safety
  net surfaces a user-facing warning — a comment isn't enough.
- **Keep raw and corrected values under different names.** Never overwrite a field
  that other consumers (especially display labels) read as the raw value.
- **A field's display format is part of its contract.** Reuse it in every new view.
- **Filter and display on the same rounded value.** `> 0` on a raw float vs. `:.1f`
  output disagree near zero.
- **Re-apply "worth showing" filters at the stage that presents results**, not only
  at an earlier ranking stage.
- **"Protect X from selection" ≠ "remove X from the field."** Apply exclusions at the
  final pick, not before shared computations others depend on.
- **Mutually exclusive sets derive from each other** rather than each from its own
  checklist.
- **Persist the full evaluated set with an explicit flag**, never just the rows that
  passed — a missing row and an excluded row are different facts.
- **Carry structure as fields; don't parse display strings** back into data.
- **External IDs are opaque keys**, never ranges to iterate.
- **"First seen in a filtered subset" ≠ "first time it happened."**
- **Sort by relevance before capping a list.**
- **A sentinel must sit outside the real domain** — `0` can't mean "unset" for a score.
- **Check validity, not just presence**, before skipping a fallback.
- **A stricter replacement check must still tolerate the missing data** the old one
  silently handled.
- **Re-check a reused constant or threshold for its new job** — a value tuned for a
  display label or one quantity isn't automatically right for an action or another.
- **Verify claims about external APIs and sibling functions** against real data or
  the code itself before relying on them.
- **Decisions about what to save belong in tested library code**, not UI handlers.

## Surgical changes

- Touch only what the task needs; match existing style.
- Remove orphans you created; leave pre-existing dead code alone.
- Report unrelated issues (and where to track them) instead of fixing them.
- Every changed line should trace to the request.

## Logging

- Use the logging framework, never `print()`, unless output *is* the product (a CLI's
  final `OK:`/`FAIL:` line, JSON on stdout).
- Prefer structured logs: a fixed message plus fields/args
  (`logger.info("Pick saved", extra={"week": week})` or `%s` args), not f-strings.
  Let the framework and handlers own formatting, levels, and truncation.
- Log events, not state dumps. Never in tight loops.
- **Error**: something broke. **Warning**: recovered from something unexpected.
  **Info**: user actions and significant events. **Debug**: off in production.

## Immutability

Prefer immutable domain models and DTOs; keep mutable state in the service layer.
