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

**ID tracker** (last number assigned): `CP-32`.

## Current branch — fix before merge

Empty right now.

## Now — blocking

Empty right now — nothing blocking.

## Backlog

- [ ] **CP-1: Enter the real 2026 late-season deadlines into the live
  deployment's Settings tab.** Confirmed against the actual 2026 Legion
  Football Pool Rules document (2026-08-27) — note this is now **three**
  weeks, not two: the 2026 rules added week 16 alongside 17-18 (rule 2:
  "EXCEPT WEEKS 16, 17 & 18"; rule 14 lists all three explicit dates).
  Values to enter via Settings once deployed:
  - Week 16: Saturday Dec 26, 2026, before 1:00 PM ET
  - Week 17: Saturday Jan 2, 2027, before 4:30 PM ET
  - Week 18: Saturday Jan 9, 2027, before 4:30 PM ET

  (Rule 14's closing line says "these final two weeks", which conflicts
  with the three weeks/three dates listed earlier in the same rule —
  treating the three explicit dates as authoritative, not the summary
  phrase, which reads as leftover wording from a prior year's version of
  this document.) `store.set_late_season_deadline()` and the Settings tab
  now accept week 16 (previously hard-blocked -- see
  `confidence_pool_principles.md`'s newest rule). **Narrowed 2026-08-27
  (usability pass):** these three values are now the Settings tab's
  default for an unconfigured week 16-18 in the 2026 season
  (`settings_tab.KNOWN_2026_LATE_SEASON_DEADLINES`) — a real visit still
  needs to happen once deployed (each week's "Save" button still has to
  be clicked to actually persist a `season_week_rules` row), but it's a
  review-and-confirm, not data entry from scratch.
- [ ] **CP-2: Verify the NAS offsite backup actually covers
  `confidence_pool_data` (the SQLite pick-history volume).** Docker named
  volumes are durable across container restarts but live under Docker's
  own data root, which may or may not be in scope for whatever backup job
  covers the NAS's shared folders. If it isn't, switch to a bind-mounted
  path under a folder the backup already covers. This is a NAS/`../nas-configs`
  configuration question, not resolvable from this repo alone.
- [ ] **CP-3: Season-long cumulative standings across all of a season's
  scored weeks.** **Narrowed 2026-08-27 (Phase 3a):** this item originally
  covered both per-week scoring and season-long totals; per-week scoring
  is done — `picks_core.score_picks()` (algorithm vs. actual, bylaws
  rules 6/7/15/16 applied) and the reported-score cross-check
  (`picks_core.check_reported_score()`, `CP-29`'s mismatch-flagging idea)
  now run on the Picks tab once a locked week's outcomes are known — see
  `docs/confidence-pool-web-app.md`'s "Weekly scoring" section and
  `docs/confidence-pool-data-model.md`'s `week_status` section. What's
  left is summing those per-week figures into a running season total
  (algorithm vs. actual) somewhere a human can see it — a new
  panel/section, reusing `score_picks`/`WeekScore` across every scored
  week in a season rather than a second computation path. Deliberately
  deferred until there's real multi-week data to make it worth building
  against — work on it "when it makes sense," per the user.
- [ ] **CP-30: Import the pool's actual score sheet (PDF or similar) to
  auto-populate `week_status.reported_score`**, cross-checking it against
  the app's computed score the same way manual entry already does
  (`picks_core.check_reported_score()`, wired up in Phase 3a). No parsing
  exists yet — manual entry via the Picks tab's "Reported score" field is
  the interim step this depends on, already built.
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
- [ ] **CP-26: Let the Picks tab UI switch between viewing a week's
  `'first'` and `'current'` snapshot** (user, 2026-08-24, flagged for a
  future feature branch — not this one). Now that both are actually
  stored (the `snapshot_type` split from the Phase 1 schema redesign),
  surface it: a toggle/selector on the Picks tab to view either
  snapshot's picks table, so "what did I first see" vs. "what's it look
  like now" is visible in the UI, not just queryable in the database.
  Applies to unlocked weeks too, not just locked ones — `'current'`
  keeps changing on every regenerate pre-lock, while `'first'` stays
  frozen from the first eligible look, so the comparison is meaningful
  either way. `store.load_week()` currently only loads `'current'`; needs
  either a `snapshot_type` parameter or a second loader for `'first'`.
  Worth considering a diff view (highlight which picks' points/confidence
  moved) rather than two flat tables side by side, but the toggle itself
  is the starting ask.
