# Project Plan — Confidence Pool

Scoped to `confidence_pool/` only. `dynasty/`'s backlog lives in
`.claude/PROJECT_PLAN_DYNASTY.md` — the two subsystems share no code (see
`CLAUDE.md`'s "Architecture") and are kept in separate plan files
deliberately, so neither accumulates the other's items by mistake. See
`docs/README.md`'s "Confidence pool" section for durable design docs; this
file is only what's left to do.

Same conventions as the dynasty plan: grouped by theme, most important
first within a group; remove an item's entry the moment it's done (the
closing commit/PR is the historical record); a durable design decision
belongs in `CLAUDE.md`, `docs/`, or a `.claude/conventions/` file, not here.

**Item IDs**: every open item carries a permanent `CP-<n>` tag, assigned
once in document order and never reused or renumbered even after the item
it names is completed and deleted. Cross-reference other items by tag
(`see CP-3`), never by list position.

**ID tracker** (last number assigned): `CP-7`.

## Current branch — fix before merge

`feature/confidence-pool-web-app` — MVP web frontend for the weekly
confidence-pool picks (see the approved implementation plan for full
scope). Cleared out when the branch merges.

Empty right now.

## Now — blocking

Empty right now — nothing blocking.

## Backlog

- [ ] **CP-7: Map team abbreviations (e.g. `LAC`) to the display names
  used on the Legion pool's own pick sheet** (e.g. "LA Chargers",
  "DENVER", "DALLAS") when rendering picks in the UI — user-flagged
  2026-08-22, high priority for the near future. The sheet's own naming
  isn't a consistent format across teams (some city+mascot, some
  city-only/all-caps), so this needs the real 32-team mapping from the
  user, not a guessed convention — do not fabricate the mapping table.
- [ ] **CP-1: Confirm/correct 2026's weeks 17–18 cutoff in `season_config`
  once the commissioner announces it.** Seeded at build time with a
  placeholder based on 2025's pattern (Saturday games, early-afternoon ET
  cutoffs) — the exact date/time is commissioner-announced each year and
  must be corrected via the Settings tab before those two weeks matter,
  not hardcoded in code.
- [ ] **CP-2: Verify the NAS offsite backup actually covers
  `confidence_pool_data` (the SQLite pick-history volume).** Docker named
  volumes are durable across container restarts but live under Docker's
  own data root, which may or may not be in scope for whatever backup job
  covers the NAS's shared folders. If it isn't, switch to a bind-mounted
  path under a folder the backup already covers. This is a NAS/`../nas-configs`
  configuration question, not resolvable from this repo alone.
- [ ] **CP-3: Join persisted weekly snapshots against real game outcomes**
  to enable what-if analysis ("what if I'd picked differently") and
  season-long scoring. Needs a source for final scores (`nfl_data_py`'s
  schedule data already carries these once games complete).
- [ ] **CP-4: Record the actual pick submitted for the current week when
  it deviates from the algorithm's recommendation.** Not something the
  user does today (deliberately trusting the algorithm, which performed
  well last season), but wanted eventually so recommended-vs-actual can be
  compared. Needs an `actual_pick` column/table added to the schema when
  this is picked up.
- [ ] **CP-5: Expose weekly pick history via a small analytics API** once
  there's an actual second consumer for it (e.g. `CP-3`'s what-if
  analysis) — likely a small FastAPI service reading the same SQLite
  store, added alongside the Streamlit container rather than replacing it.
- [ ] **CP-6: Fill in `football_enhanced.py`'s other stubbed weight
  functions** (injury impact, weather/altitude, sentiment) as real signals
  in `picks_core.py`, if the Vegas-odds-only approach ever stops being
  sufficient. Deliberately deferred — the pure-odds approach already
  placed 7th of 100+ last season, so this isn't urgent.
