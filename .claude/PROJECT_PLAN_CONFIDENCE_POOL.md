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

**ID tracker** (last number assigned): `CP-12`.

## Current branch — fix before merge

`feature/confidence-pool-web-app` — MVP web frontend for the weekly
confidence-pool picks (see the approved implementation plan for full
scope). Cleared out when the branch merges. Reviewed 2026-08-22
(assistant valuation review).

- [ ] **CP-8: Excluded games don't persist — an unchecked game silently
  reverts to "included" on the next page load.** `panels/picks_tab.py`'s
  "Regenerate picks" button and the deadline auto-lock (`CP-9`) both call
  `store.save_week()` with only the *included* subset of `auto_games`
  (`chosen.assign(included=True)`), so a game the user unchecked is never
  written to `weekly_games` at all — not stored with `included=0`, just
  absent from the table entirely. `included_map` (rebuilt from
  `saved_games` on the next load) therefore has no entry for that game,
  and `included_map.get(row["game_id"], True)` falls back to *True* —
  silently re-checking a game the user deliberately excluded, the moment
  a new session/reload happens (a fresh browser session, a container
  restart, or the automatic lock in `CP-9`/`CP-10`). This defeats the
  documented purpose of the checkboxes ("a normal part of reviewing each
  week," not just an escape hatch — `docs/confidence-pool-web-app.md`).
  Fix: pass the *full* `auto_games` frame to `save_week()` with a real
  per-row `included` column reflecting the checkbox state, and rank only
  the included subset — the schema (`weekly_games.included`) already
  supports this; only the caller never uses it.
- [ ] **CP-9: Deadline auto-lock always recomputes from live odds
  instead of reusing the last manually-generated snapshot.**
  `panels/picks_tab.py`'s auto-lock block re-runs `pc.rank_games()`
  against freshly-fetched odds at whatever moment the page happens to
  load after the deadline, even when `saved_picks` already holds a
  snapshot from an earlier "Regenerate picks" click.
  `docs/confidence-pool-web-app.md` documents the intended behavior as
  "locks the **last-generated snapshot** (or, if nothing was ever
  generated, computes one final time)" — the code doesn't do that; it
  *always* recomputes. Since moneylines move over the course of a week,
  the snapshot that actually gets locked (and becomes the permanent
  historical record `CP-3`/`CP-4` depend on) can silently differ from
  the picks the user actually saw and submitted to the pool earlier.
  Fix: if `saved_picks` is non-empty, lock it as-is
  (`store.save_week(conn, season, week, saved_games, saved_picks, now,
  lock=True)`); only recompute from `auto_games` when nothing was ever
  generated.
- [ ] **CP-10: Auto-lock silently no-ops (never locks, no warning) if
  odds are still pending for any selected game at the deadline.** The
  auto-lock block only calls `store.save_week(..., lock=True)` `if
  pending.empty`; when a game's moneyline hasn't posted yet, nothing is
  saved, `locked` stays `False`, and the function falls through to the
  normal unlocked edit view with no indication the deadline has already
  passed. Most likely for weeks 17-18, where `configured_deadline` is
  deliberately set *earlier than any of that week's real kickoffs* (the
  bylaws' own example: a Saturday cutoff, potentially a day or more
  before some of that week's games) — exactly the situation where Vegas
  may not have posted lines for every selected game yet. The result: the
  app's own safety net (the entire reason this web app exists — see the
  doc's opening motivation) can fail precisely when it's most needed,
  with the UI giving no sign anything's wrong. Fix: on a pending-odds
  auto-lock attempt, surface an explicit warning ("deadline passed but
  odds aren't posted for: ...") so the gap is visible instead of silent.

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
- [ ] **CP-11: Extract the deadline/lock decision and inclusion-merge
  logic out of `panels/picks_tab.py` into `picks_core.py` as a plain,
  Streamlit-free function** (assistant valuation review, 2026-08-22).
  `CP-8`/`CP-9`/`CP-10` all live in code with zero test coverage —
  `tests/confidence_pool/` covers `picks_core.py` and `store.py`
  thoroughly, but the `panels/` modules have none, and this is exactly
  the kind of business logic (not UI rendering) that belongs in the
  tested core library per this project's own split (`picks_core.py` as
  the library, `panels/` as thin orchestrators — see `CLAUDE.md`'s
  Architecture section). A function like `resolve_week_lock(auto_games,
  saved_games, saved_picks, status, now, deadline) -> LockDecision`
  would keep `picks_tab.py` a thin orchestrator and make `CP-8`-`CP-10`'s
  fixes verifiable by a unit test instead of only by manual QA.
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
  arbitrary when it happens).
