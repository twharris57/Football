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

**ID tracker** (last number assigned): `CP-23`.

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
- [ ] **CP-12: Revisit the vig-removal method for extreme favorites, and
  consider multi-book consensus lines** (assistant valuation review,
  2026-08-22). `compute_probability` + `rank_games`'s proportional
  normalization (`home_prob / (home_prob + away_prob)`) is the standard
  "multiplicative" de-vig method, reused unchanged from
  `football_enhanced.py` — reasonable for most games, but known in the
  sports-betting literature to distort implied probability more than
  alternatives (e.g. Shin's method, which corrects for the "longshot
  bias") specifically for large favorites/underdogs (moneylines beyond
  roughly +/-300). Also worth a look: `nfl_data_py`'s moneyline
  presumably reflects one sportsbook (or an aggregate) rather than a
  cross-book consensus/closing line, typically a lower-noise input for
  probability estimation. Neither is urgent — the pure-odds approach
  already placed 7th of 100+ last season (see `CP-6`) — but worth a real
  backtest against last season's results before investing further,
  rather than assuming either change would actually improve rank order
  in practice. While touching this, also add a deterministic secondary
  tiebreaker to `rank_games`'s sort — it currently falls back to
  schedule order on an exact confidence tie (rare with real odds, but
  arbitrary when it happens). **Refined 2026-08-23 (user, PR #46):** once
  the basics are in place, backtest by opening up the 2025 season and
  having the user input last season's actual picks, so the current
  algorithm's real results are on record to compare a methodology change
  against — needs `CP-3` (join snapshots against outcomes) and `CP-13`
  (store the raw inputs a pick was generated from) as prerequisites.
- [ ] **CP-13: Store the raw inputs a pick was generated from, plus room
  for supplemental fields, not just the final points/predicted-winner
  output** (user, PR #46 review, 2026-08-23). Right now `weekly_picks`
  only holds the derived result (`points`, `predicted_winner`,
  `confidence`); comparing an alternative algorithm (`CP-6`, `CP-12`)
  against what actually happened requires re-deriving the original raw
  moneylines from `weekly_games` and hoping the math hasn't changed
  underneath. Store the inputs (or at least a versioned pointer to which
  algorithm/formula produced a row) alongside the output, so a future
  methodology change can be backtested against exactly what was used at
  the time, not an approximation of it. Ties into `CP-12`'s backtest
  idea and the broader schema-normalization pass (`CP-19`-`CP-23`).
- [ ] **CP-14: Replace the Picks tab's season/week `+`/`-` number inputs
  with dropdowns, scoped to real available values, with better
  defaults** (user, PR #46 review, 2026-08-23). Season should offer only
  seasons that actually exist in `season_config`/have data, not an
  arbitrary 2020-2100 range; week should offer only that season's real
  weeks. Default to the current season/week during the season; in the
  off-season, default to the last week of the previous season if the new
  season hasn't been opened yet (see `CP-17`), or the first week of the
  new season once it has. Also label weeks with their date span (e.g.
  "Week 1 (Sept 13-14)") instead of a bare number, so it's clear what
  span of the calendar a week actually covers.
- [ ] **CP-15: Flag when the deadline auto-lock's "one final computed"
  fallback snapshot was generated well after the deadline — potentially
  after some of that week's games have already kicked off or
  finished** (user, PR #46 review, 2026-08-23). `resolve_week_lock()`'s
  fresh-computation fallback (when nothing was ever manually generated
  for the week) only fires once the deadline has passed, but if the app
  isn't opened again until days later, some/all of that week's games may
  have already been played by the time it runs. Needs investigating what
  `nfl_data_py`'s moneyline field actually returns for an in-progress or
  completed game (a frozen pregame closing line is fine to treat as a
  real prediction; a live in-play line would not be) before deciding
  whether to just timestamp-flag the record or block/warn more
  aggressively. This is a narrower case than `CP-9`/`CP-10` already fixed
  (those apply whenever *anything* was manually generated first; this is
  specifically the "the week was never touched by a human at all" path).
- [ ] **CP-16: Give the Picks tab an in-app explanation of the
  confidence/odds methodology, plus an expandable per-pick detail
  view** (user, PR #46 review, 2026-08-23). Two related asks: (1)
  somewhere in the app (its own section, or the bottom of the Picks tab)
  a plain-language writeup of how `compute_probability`/`rank_games`
  turns moneylines into points, so the methodology isn't only documented
  in `docs/confidence-pool-web-app.md`; (2) an expandable row/detail view
  per pick showing the actual inputs (raw moneylines) and intermediate
  math, not just the final points/predicted-winner/confidence columns —
  depends on `CP-13` storing those inputs if it should also work for
  historical weeks, not just the currently-generated one.
- [ ] **CP-17: Replace the Settings tab's season number-input + "Set as
  active season" button with a readonly display of the current season
  plus an "Open {year} season" button** (user, PR #46 review,
  2026-08-23). The season *year* itself is informational, not something
  that needs free-form editing — a readonly display is enough. The real
  action is opening the next season once the current one ends; a button
  that only enables once that's true (rather than a bare number input
  accepting anything 2020-2100) matches the actual workflow and prevents
  accidentally activating the wrong year. Once this exists reliably,
  revisit whether `picks_core.default_season_year()`'s date-based
  guessing fallback is still needed as anything more than a rare
  last-resort — `streamlit_app.py` already prefers `season_config`'s
  active flag over it, this would just make that flag more consistently
  populated.
- [ ] **CP-18: Show a semantic version number alongside the git-SHA
  build indicator** (user, PR #46 review, 2026-08-23). The footer
  currently shows only `GIT_SHA` (see `confidence_pool/Dockerfile`) —
  useful for confirming a deploy picked up the latest image, but not a
  quick human-readable "is this the latest version" signal the way a
  semantic version tag would be. This repo doesn't currently use semantic
  versioning at all (per `git_workflow_simple.md`'s "Versioning" section,
  tags are opt-in, bumped only on a real release) — worth deciding
  whether that convention gets adopted for real, and whether it applies
  to just this app or the dynasty app too, before wiring a version string
  into the footer.
- [ ] **CP-19: Move bylaws-derived constants (`SUNDAY_AFTERNOON_CUTOFF`,
  `LATE_SEASON_WEEKS`) into per-season database configuration instead of
  hardcoded Python constants** (user, PR #46 review, 2026-08-23). Part of
  the eventual confidence-pool database-design pass the user flagged
  (see `CP-7`'s note: "once we get team names in place, the next thing is
  probably a database design task where we look at this in great detail
  and really think about what we need to be tracking from day 1") — see
  also `CP-13`, `CP-20`-`CP-23`, all part of the same eventual pass.
- [ ] **CP-20: Split the SQL schema into a dedicated namespace/module for
  schema maintenance, including real migration scripts** (user, PR #46
  review, 2026-08-23). `store.SCHEMA`'s single `CREATE TABLE IF NOT
  EXISTS` script works for an app with no released schema history yet,
  but has no path for evolving a table's shape once real data exists in
  it. Part of the database-design pass — see `CP-19`.
- [ ] **CP-21: Normalize the weeks-17/18 deadline exception into its own
  table instead of dedicated `week17_deadline`/`week18_deadline`
  columns** (user, PR #46 review, 2026-08-23). Would also make the
  scheme extensible if a future season's bylaws add an exception for a
  different week (e.g. week 16) without a new column per week. Part of
  the database-design pass — see `CP-19`.
- [ ] **CP-22: Further normalize `weekly_games`** (e.g. a dedicated teams
  table) as the schema matures (user, PR #46 review, 2026-08-23). Part of
  the database-design pass — see `CP-19`.
- [ ] **CP-23: Write a dedicated database-design doc once the schema
  settles** (user, PR #46 review, 2026-08-23) — covering the outcome of
  `CP-19`-`CP-22` and any other schema decisions made along the way,
  mirroring the dynasty subsystem's `docs/dynasty-data-model.md`. Not
  worth starting until the schema questions above have actually been
  decided, per the user's own framing (see `CP-19`).
