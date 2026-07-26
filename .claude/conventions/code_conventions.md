# Code Conventions

Universal conventions that apply regardless of language or framework. Language-specific
files reference these rather than repeat them.

## Security

- **Never commit secrets.** API keys, passwords, tokens, certificates, and connection
  strings with credentials must never appear in committed code — regardless of whether
  the repository is public or private. Use environment variables, secrets management
  services, or vault tools at runtime.
- **If a secret is accidentally committed, rotate it immediately.** Removing it from
  history is insufficient — treat the credential as compromised from the moment it was
  committed.
- Add known secret file patterns to `.gitignore` (`.env`, `*.pem`, `credentials.json`,
  etc.), but do not rely on `.gitignore` alone. Pre-commit hooks or tools like
  `git-secrets` provide a second safety net.
- Never log secrets or PII — see the Logging section below.

## Code Hygiene

- No commented-out code in committed files.
- No `TODO` or `FIXME` comments in committed code — open a work item in the project
  tracker instead.
- No debug-level log statements left in production code paths by default (see Logging).

## Inline Comments

Add a comment only when the *why* is non-obvious — a hidden constraint, a subtle
invariant, a workaround for a known external limitation or bug. Never describe what
the code does; well-named identifiers do that.

## Code Smells and Design Principles

### Prefer the simplest correct solution

If a straightforward approach works, use it. Don't introduce a pattern, layer of
indirection, or abstraction that isn't required by the current problem. Clever code
has a high maintenance cost and a low return.

### Avoid premature abstraction

Wait until you have three or more concrete cases before extracting a shared abstraction.
A wrong abstraction is harder to undo than duplication — it couples unrelated things and
obscures intent. When in doubt, repeat yourself once more and wait.

### Don't design for hypothetical requirements

Implement what is needed now. Future-proofing against scenarios that may never arrive
adds complexity without value and frequently guesses the future wrong.

### No half-finished implementations

Don't commit stub methods that swallow input silently, placeholder logic that returns
hardcoded values, or anything marked "implement later." Either implement it properly
or don't include it. Incomplete code in the codebase creates false confidence and
unpredictable runtime behavior.

### Avoid exotic workarounds

If you find yourself reaching for reflection, metaprogramming, runtime code generation,
or other advanced mechanisms to solve a problem that is fundamentally simple, the design
needs rethinking. These tools have legitimate uses, but their presence in ordinary
business logic is a strong signal that the abstraction is wrong.

### Prefer consistency over novelty

Follow existing patterns in the codebase before introducing new ones. Introducing a
second way to do something that already has an established pattern creates maintenance
burden and cognitive overhead for everyone who reads the code later.

### Apply the senior engineer test

Before considering a solution done, ask: *would a senior engineer look at this and say it's overcomplicated?* If yes, simplify. This is not about cleverness — it's about the next person who has to read, debug, or extend this code.

### Don't stack symptomatic fixes

When a bug fix doesn't fully hold and requires another fix — especially when each fix
is a conditional or procedural block guarding against the same failure mode in a
slightly different way — stop and ask whether the underlying data model or abstraction
is the real problem.

Layered symptomatic fixes share two failure modes: they are hard to follow because the
same logical concern is scattered across multiple guards, and they are rarely exhaustive
because each guard only catches the specific case that prompted it. The next edge case
produces another guard.

A design that correctly models the domain eliminates an entire class of symptoms rather
than catching each manifestation individually. Before adding a second guard for the same
symptom, ask: *what precondition about the data, if enforced at the source, would make
this guard unnecessary?*

## Surgical Changes

When editing existing code, touch only what the task requires.

- **Don't improve adjacent code.** Don't refactor, reformat, or "clean up" code that
  isn't directly involved in the change. Match the existing style even if you'd do it
  differently. Consistency outweighs personal preference.
- **Clean up only your own orphans.** If your changes leave behind unused imports,
  variables, or functions that *you* introduced, remove them. Don't remove pre-existing
  dead code unless that is the explicit task.
- **Report unrelated issues; don't fix them.** If you notice technical debt, a latent
  bug, or a code smell while working on something else, surface it — then leave it alone.
  Unilateral cleanup during unrelated work makes diffs hard to review and can introduce
  regressions.
- **Track what you surface.** When you report a detected issue, note that it should be
  tracked somewhere. How that works depends on the project — check the project's CLAUDE.md
  for the issue tracker (Jira, GitHub Issues, a `DESIGN_NOTES.md` with a technical debt
  section, etc.). If no tracker is specified, flag it to the user so they can decide.
- **The diff test.** Every changed line should trace directly to the user's request. If
  you can't explain why a line changed, it shouldn't have changed.

## Logging

### Philosophy

- **Never log user-entered data, PII, or security-sensitive values.** Use opaque
  identifiers (e.g., a record ID) instead of names, contact details, or any value
  the user typed.
- Never log in tight loops, on every frame or render cycle, or on any high-frequency
  code path.
- Log *events*, not *state dumps*. A message describes what happened ("order rejected")
  not a snapshot of data at that moment ("status=REJECTED amount=99.99 userId=...").

### Log Levels

| Concept | When to use |
|---------|-------------|
| **Error** | Exceptions and unrecoverable failures — something broke that requires attention |
| **Warning** | Unexpected but recoverable — the system adapted but something was off |
| **Info** | User-initiated actions or significant application events in the normal flow |
| **Debug** | Diagnostic detail that is suppressed by default in production environments. Enabling debug output in production is a deliberate operational decision (e.g., during active incident investigation) — not the standard running state |

Level names vary by platform (`Information` in .NET, `WARNING` in Python, `WARN` in
SLF4J, etc.) — see the language-specific file for exact identifiers and framework setup.

## Immutability

Prefer immutable representations for domain models and data transfer objects. Mutable
state belongs in the application's service or state layer, not in value objects or models.
The specific mechanism varies by language — see the language file for idiomatic approaches.
