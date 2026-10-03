# /confidence-pool-review

Domain review of the confidence-pool app (`confidence_pool/picks_core.py`, `store.py`,
`panels/`, and docs). Counterpart to `/valuation-review`.

```
/confidence-pool-review              # open PR for the current branch
/confidence-pool-review <branch>     # a specific branch/PR
/confidence-pool-review full         # the whole app as it stands
```

**Persona, two lenses:**

- **Betting analyst** — odds conversion, de-vig methods, ranking by edge, small samples.
- **Reliability engineer** — the deadline lock runs unattended. What happens when its
  assumptions fail, and does the failure announce itself?

## Instructions

1. **Scope.** PR mode: `git diff <base>...<branch>` and `git log <base>..<branch>`.
   Full mode: read the modules and `docs/confidence-pool.md` end to end.
2. **Check each function against `confidence_pool_principles.md` and
   `code_conventions.md`**, especially:
   - a second odds→ranking path instead of `rank_games`
   - selection changes not checked against the bylaws and real schedule data
   - save paths around the deadline that bypass `resolve_week_lock`
   - persisting only the passing rows
   - unattended paths that can no-op silently
   - decision logic landing in `panels/` (untested) instead of `picks_core`/`store`
   - season/week edges: late-season weeks, the March season-year cutoff, naive datetimes
   - tests that only cover the expected path
   - backlog IDs or history narrated in code, comments, or docs
3. **Tier findings:** (1) could produce wrong points, lost records, or a silent safety-net
   failure, (2) bounded imprecision, (3) minor edge case.
4. **File them in `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`.** Tier 1 → "Current
   branch — fix before merge". Tiers 2–3 → Backlog with the next `CP-` ID. Keep each item
   to a few lines.
5. **Add a principle only for a new, recurring pattern.** One-line rule plus a short
   reason, no incident story. Domain rules go in `confidence_pool_principles.md`, generic
   ones in `code_conventions.md`.
6. **Update `docs/` only if documented behavior or a known limitation changed** — edit
   the section in place.
7. **Commit to the branch under review, never `main`.** Stage only files this review
   touched. Push. Don't merge or implement fixes unless asked.
8. **Report** findings most-severe first, say what's blocking, and offer to fix tier 1.
