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

**ID tracker** (last number assigned): `CP-25`.

## Current branch — fix before merge

`feature/confidence-pool-db-design` (PR #49) — Phase 1 schema redesign:
normalizes `seasons`/`teams`/`games` reference data and moves the
weeks-17/18 bylaws exception from `LATE_SEASON_WEEKS` into
`season_week_rules`. Cleared out when the branch merges.

- [ ] **CP-24: Weeks 17-18 silently fall back to the `'standard'`
  Sunday/Monday-only selection rule until a human has visited the
  Settings tab and set that season's deadline** (assistant
  confidence-pool review, 2026-08-23). Before this branch,
  `LATE_SEASON_WEEKS` applied the bylaws' "every game counts, no weekday
  filter" exception unconditionally by week number — only the *deadline*
  had a graceful "fall back to earliest kickoff" default when
  unconfigured. This branch collapsed both facts into one
  `season_week_rules` row, but the only writer is
  `store.set_late_season_deadline()`, called solely from a Settings-tab
  button click — nothing seeds the row automatically, and
  `panels/picks_tab.py`'s fallback (`week_rule["selection_rule"] if
  week_rule else "standard"`) silently applies `'standard'` for an
  unconfigured week 17/18, excluding real games (e.g. a Saturday game)
  the bylaws say should count and producing a wrong point assignment for
  real money — with no warning, since the `st.info` banner about the
  week's special rule only renders `if week_rule` (i.e., after the row
  already exists). `current_week()` will land on week 17 automatically
  as the season progresses, with nothing prompting the user to configure
  Settings first, so this is a near-certain hit each new season unless
  caught proactively. Fix by seeding a default `season_week_rules` row
  (`selection_rule='all_games'`, `deadline_override=NULL`) for weeks
  17/18 the same way `teams` is seeded (`_seed_default_teams`'s `INSERT
  OR IGNORE` pattern — safe to reseed, never clobbers a later edit), or
  by having `picks_tab.py` fail loud/warn rather than silently defaulting
  to `'standard'` for weeks 17/18 specifically. See
  `confidence_pool_principles.md`'s new "moving a hardcoded domain rule
  into configurable data" rule. Also update
  `docs/confidence-pool-data-model.md`'s "Static assumptions" table entry
  for this, which currently implies seed data already covers it. Relates
  to `CP-1` (the deadline *value* itself still needs yearly correction
  regardless of this fix).
- [ ] **CP-25: The deadline auto-lock's snapshot-reuse path stamps the
  lock-evaluation time onto the reused snapshot's `generated_at`/
  `captured_at`, overwriting its true original generation time** (assistant
  confidence-pool review, 2026-08-23). `resolve_week_lock()` correctly
  reuses a prior `saved_picks` snapshot's *values* rather than
  recomputing, but `panels/picks_tab.py` calls
  `store.save_week(conn, season, week, outcome.games, outcome.picks, now,
  lock=True)` — passing `now` (the moment the deadline-passed check ran)
  as the single `generated_at` argument regardless of whether the
  snapshot being persisted is freshly computed or reused. `save_week()`
  stamps that value onto both `week_status.generated_at` and every
  `'current'`-snapshot `weekly_games.captured_at` row, silently
  overwriting the reused snapshot's real generation/capture time with an
  unrelated timestamp — corrupting exactly the fact (when was this
  actually generated/captured) the new `'first'`/`'current'` snapshot
  split exists to make queryable ("did odds move between first review
  and lock"). Fix by threading the reused snapshot's own timestamp
  through `LockOutcome` (e.g. a `generated_at` field) instead of letting
  the caller substitute `now()`. No test exercises this path at the
  `save_week()` call-site level, which is also an instance of
  `confidence_pool_principles.md`'s "business logic belongs in the tested
  library, not the panel" rule — deciding which timestamp is correct to
  persist is business logic currently living, untested, in
  `picks_tab.py`.

## Now — blocking

Empty right now — nothing blocking.

## Backlog

- [ ] **CP-1: Confirm/correct 2026's weeks 17–18 cutoff in
  `season_week_rules` once the commissioner announces it.** Seeded at
  build time with a placeholder based on 2025's pattern (early-afternoon
  ET cutoffs, ahead of that week's real kickoffs) — the exact date/time
  is commissioner-announced each year and must be corrected via the
  Settings tab before those two weeks matter, not hardcoded in code.
- [ ] **CP-2: Verify the NAS offsite backup actually covers
  `confidence_pool_data` (the SQLite pick-history volume).** Docker named
  volumes are durable across container restarts but live under Docker's
  own data root, which may or may not be in scope for whatever backup job
  covers the NAS's shared folders. If it isn't, switch to a bind-mounted
  path under a folder the backup already covers. This is a NAS/`../nas-configs`
  configuration question, not resolvable from this repo alone.
- [ ] **CP-3: Join persisted weekly snapshots against real game outcomes**
  to enable what-if analysis ("what if I'd picked differently") and
  season-long scoring. The data groundwork is done as of the Phase 1
  schema redesign — `games.home_score`/`away_score` backfill automatically
  via `store.sync_game_outcomes()` on every Picks-tab load — what's left
  is the actual what-if/scoring logic and UI to consume it.
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
  against — needs `CP-3` (join snapshots against outcomes) as the
  remaining prerequisite; raw-input/algorithm-version storage is done
  (`algorithm_versions`, Phase 1 schema redesign).
- [ ] **CP-14: Replace the Picks tab's season/week `+`/`-` number inputs
  with dropdowns, scoped to real available values, with better
  defaults** (user, PR #46 review, 2026-08-23). Season should offer only
  seasons that actually exist in `seasons`/have data, not an
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
  the raw moneylines needed for this are already stored per-snapshot in
  `weekly_games`, including for historical weeks, not just the
  currently-generated one (resolved by the Phase 1 schema redesign — see
  `docs/confidence-pool-data-model.md`).
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
  last-resort — `streamlit_app.py` already prefers `seasons.active`
  over it, this would just make that flag more consistently populated.
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
