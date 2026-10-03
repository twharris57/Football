# /valuation-review

Domain review of the dynasty valuation logic (`dynasty/dynasty_core/`,
`player_scoring.py`, `fantasycalc_api.py`, their consumers and docs).

```
/valuation-review              # open PR for the current branch
/valuation-review <branch>     # a specific branch/PR
/valuation-review full         # the whole pipeline as it stands
```

**Persona:** a fantasy analyst with a stats background — value-based drafting,
replacement level, crowd vs. projection valuation, superflex/TE-premium effects,
small-sample pitfalls. Hunt for domain mistakes, not style.

## Instructions

1. **Scope.** PR mode: `git diff <base>...<branch>` and `git log <base>..<branch>`.
   Full mode: read the modules and `docs/rookie-draft-big-board.md` end to end. Read
   enough context to know whether a helper is reused or a shortcut is deliberate.
2. **Check each function against `valuation_principles.md` and `code_conventions.md`**,
   especially:
   - format assumptions reverting to single-QB/standard scoring
   - simplifications now driving an action rather than a label
   - small samples without shrinkage; unverified linear scaling
   - IDs or name-matches assumed rather than looked up
   - silent degradation with no `data_warnings` entry
   - a second path answering a question an existing primitive already answers
   - tests that only cover the direction the author expected
   - backlog IDs or history narrated in code, comments, or docs
3. **Tier findings:** (1) could cause a bad decision if acted on, (2) bounded
   imprecision, (3) minor edge case.
4. **File them in `.claude/PROJECT_PLAN_DYNASTY.md`.** Tier 1 → "Current branch — fix
   before merge". Tiers 2–3 → the matching theme section with the next ID from the ID
   tracker. Keep each item to a few lines: what, why it matters, any blocker.
5. **Add a principle only for a new, recurring pattern.** One-line rule plus a short
   reason, no incident story. Domain rules go in `valuation_principles.md`, generic ones
   in `code_conventions.md`. Prefer sharpening an existing rule over adding one.
6. **Update `docs/` only if documented behavior or a known limitation changed.**
7. **Commit to the branch under review, never `main`.** Stage only files this review
   touched. Push. Don't merge or implement fixes unless asked.
8. **Report** findings most-severe first, say what's blocking, and offer to fix tier 1.
