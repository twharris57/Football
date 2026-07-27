# Project Plan

Tracks what's actively being worked on, what's queued up next, and longer-range
ideas for this project. When a task is completed, write it up as a design doc
in `docs/` (what was built and why, key decisions) and remove it from this file.

## Active

- **Pre-draft hardening for Sunday's live draft (2026-08-02)** — findings from a
  multi-agent code review (2026-07-26) of `feature/valuation-recompute`,
  covering valuation logic, backend correctness/performance, test coverage,
  deployment readiness, and draft-day UX. Prioritized by what actually blocks
  or risks Sunday vs. what can wait.

  **Must fix before Sunday:**
  1. ⏳ **Synology deploy hasn't happened at all yet — needs the user's own
     action, can't be done from here.** No SSH/credentials to the NAS.
     Code-side prerequisites confirmed ready: `docker-publish.yml` triggers
     correctly on push to `main` and bakes `GIT_SHA` into the image for the
     footer version check; `Dockerfile` builds a non-root, healthchecked
     image with the `nfl_data_cache` volume mount point present. Once merged
     to `main`: confirm the GHCR build goes green (`gh run list` /
     `gh pr checks`), then on the NAS: deploy, verify the running
     container's footer git SHA matches, and pre-warm the multiplier cache
     with `python scripts/derive_position_multipliers.py` ahead of draft
     day, not live (a cold cache means a 1-2 minute `nfl_data_py` pull on
     first load — see item 2, now fixed, for why that's no longer triggered
     by the app itself). The CLI (`rookie_draft.py`, no Docker) remains the
     safer fallback regardless of how the deploy goes.
  2. ✅ **Decoupled "Force full refresh" from the scoring-multiplier
     recompute.** `dynasty_core.gather_state` no longer passes
     `force_refresh=True` to `player_scoring.get_multipliers` at all — the
     Streamlit/CLI "force full refresh" action now only busts the fast
     Sleeper players cache (~4s, confirmed by timing directly, down from
     ~33s). The only way to recompute the multiplier cache is running
     `python scripts/derive_position_multipliers.py` directly, ahead of
     time — matches item 1's "pre-warm before draft day, not live" plan
     exactly.
  3. ✅ **Clamped the per-player scoring ratio.** `player_scoring._sane_ratio`
     rejects a ratio computed from a near-zero/negative pooled
     `baseline_points` (`<= 1.0`) or landing outside `MULTIPLIER_BOUNDS`
     (`[0.5, 2.0]` — real observed ratios across 332 players land in
     `[1.08, 1.61]`, comfortably inside), falling back to the position
     average (then the hardcoded constant) instead of feeding a nonsense
     number into `adj_value`. Covered by `tests/test_player_scoring.py`
     (`TestSaneRatio`).
  4. ✅ **Fixed the Streamlit cache-key bug in `load_state`.** Was keyed on
     the raw force-refresh button's return value, which is only `True` on
     the exact run it was clicked — any later rerun (e.g. opening an
     expander) saw `False` again, changing the cache key and silently
     re-fetching both APIs for no reason. Now keyed on
     `st.session_state.force_refresh_pending`, a durable flag set once per
     click and stable across reruns. Verified directly: patched
     `gather_state` with a call counter through an `AppTest` run — a plain
     rerun immediately after a force-refresh click no longer adds a call.
  5. ✅ **Verified `bye_week_by_team('2026')` returns all 32 teams** — ran it
     directly against the real 2026 schedule; every team resolved to
     exactly one bye week, nothing dropped. No bug found; nothing to fix.

  **Worth doing this season (not blocking Sunday) — all done, 2026-07-26:**
  - ✅ CLI now catches `ValueError`/`TypeError` (e.g. a typo'd `--username`)
    with a clean message and exit, instead of an ugly traceback or an
    infinite retry loop that can't fix a bad input. Streamlit already
    handled this the same way.
  - ✅ `gather_state` now returns `data_warnings: list[str]`, surfaced as
    `st.warning`/CLI `WARNING:` lines whenever byes, handcuffs, or the
    scoring multipliers silently fall back — no longer indistinguishable
    from "no conflicts found."
  - ✅ `fantasycalc_api.get_dynasty_values` now disk-caches (12h TTL, keyed
    by `numQbs`/`numTeams`/`ppr`), tied to force-refresh — a plain "Refresh"
    no longer re-hits it every time.
  - ✅ `bye_week_by_team` (24h TTL) and `handcuff_map` (12h TTL) now disk-cache
    the same way, also tied to force-refresh. Caught and fixed a real bug
    while adding this: bye weeks are `numpy.int64` from the schedule
    dataframe, not JSON-serializable — cast to `int` before caching.
  - ✅ Added an end-to-end `TestMultiRoundPlan` test — a synthetic 2-round
    scenario confirming a true positional need (an empty QB slot) is
    correctly filled before a same-position depth upgrade, and that each
    round's pick correctly carries into the next.
  - ✅ Draft Plan tab's methodology caption is now inside a closed
    `st.expander("How this works")`.
  - ✅ Already done via the earlier collapsible-sections redesign (✅/🔜/⚠️
    icons) — no separate work needed.
  - ✅ Confirmed via a full 61-key dump of the real `scoring_settings`: no
    missed per-game yardage bonuses, but found a real, previously-uncorrected
    gap — `pass_int_td: -6.0` (an extra penalty when a QB's interception is
    returned for a touchdown, on top of the flat `pass_int` rate) — fixed in
    `player_scoring._pick_six_penalty_points`, same play-by-play approach as
    the long-play bonuses.
  - ✅ `lineup_breakdown`, `season_average_starter_value`, and
    `rank_by_marginal_value` (plus `recommend_drop`, which the last two call
    into and shares the same bug) now all exclude the roster's current
    taxi/IR players from ever winning a starting slot or being misclassified
    as a "starter" — verified this has real, visible effect on the actual
    league's live draft-plan output, not just a theoretical risk. Doesn't
    attempt to model taxi/active transitions for newly-drafted candidates
    mid-simulation (already an accepted simplification elsewhere - see
    `roster_total_capacity`'s docstring).

  **Follow-up fixes and UI polish (2026-07-26, user re-review of the above):**
  - ✅ **Found and fixed a real capacity-accounting bug while verifying the
    taxi/IR drop-eligibility fix above.** `roster_total_capacity()` summed
    active-roster + taxi slots only, omitting `reserve_slots` — so an
    existing IR occupant's headcount silently ate into active/taxi
    capacity instead of its own bucket. Verified directly: a roster with
    one IR player and a genuinely open taxi slot was misread as "no room,"
    forcing a nonsensical recommendation to cut a real active starter
    instead of just placing the new candidate in the open taxi slot. Fixed
    by including `reserve_slots` in the ceiling; regression test added
    (`TestCapacityAwareDrop::test_reserve_slots_count_toward_total_capacity`).
    Separately confirmed (with a direct repro) that taxi players themselves
    were never excluded from the drop-candidate pool — that part already
    worked correctly.
  - ✅ Added a scoring-multiplier **prewarm control to the web app**:
    "Refresh" stays the single cheap button; a new "Advanced refresh"
    sidebar expander has a players/values checkbox (fast, default on) and
    a separate scoring-multiplier checkbox (slow, 1-2 min, default off) —
    `gather_state` gained an independent `force_scoring_refresh` parameter
    so the two are never accidentally coupled. Verified directly with a
    patched call-counter that checking only the scoring box actually
    triggers `force_refresh=True` on `player_scoring.get_multipliers`.
  - ✅ Every table now shows human-readable column headers (`cols()` helper
    + `st.dataframe`'s `column_config`), without renaming the underlying
    DataFrame columns.
  - ✅ "How this works" is now consistent across all 5 methodology sections
    (Draft Plan, Draft Board, Roster Value Analysis, Bye Week Impact,
    Weekly Gaps) and reformatted from run-on prose into bulleted
    term-definition lists for readability.
  - ✅ Roster Needs' index column now displays as "Pos" instead of the raw
    `pos` field name (via `column_config`'s `_index` key).

  **Next-year ideas (not worth the time now):**
  - Handcuff proxy (depth-chart rank 2) has real false-positive risk in
    modern RB committees — informational field only, not worth revisiting
    pre-draft.
  - Dedupe/log on `gsis_id` collisions in the ID-crosswalk join
    (`player_scoring.py:230-232`, `dynasty_core.py:487-488`).
  - `sleeper_api`/`fantasycalc_api` retry and cache-TTL unit tests — folds
    into the existing "Broader test coverage" idea below.
  - Split the generic "Couldn't reach Sleeper/FantasyCalc" error message to
    name which service actually failed.
  - Exclude a candidate from its own drop-simulation in `recommend_drop`
    (theoretically possible, vanishingly unlikely to surface as a top pick).

- **Valuation algorithm improvements** (branch: `feature/valuation-improvements`)
  — sequenced deliberately, not independent workstreams:
  1. ✅ **E — refresh the QB/TE multiplier's data basis.** Pooled across 3
     seasons instead of one. Done; see `docs/rookie-draft-big-board.md`.
  2. ✅ **B — full per-player scoring recompute for players with real NFL
     history.** Replaced the position-level multiplier with a per-player one
     (`player_scoring.py`), resolving the open "blend recomputed points with
     rookie market value" question by not introducing a second value scale —
     `fc_value_by_sleeper_id` bakes the corrected multiplier into `adj_value`
     once, at the single choke point every ranking function already reads.
     Done; full methodology in `docs/rookie-draft-big-board.md`.
  3. **A — finer position/play-style multiplier buckets, rescoped to
     rookies only.** Deliberately sequenced after B, not before — a
     veteran-inclusive version of this would mostly be thrown away once B
     replaces the multiplier for anyone with real stats. `import_combine_data`
     (confirmed available) gives real per-rookie athletic profiles — a
     usable classification signal (mobile vs. pocket QB, etc.) without
     needing college stats, which we don't have access to.
  4. **D — blend in KeepTradeCut as a second market source**, time
     permitting. `import_ids()` only gives a `ktc_id` crosswalk column,
     not actual KTC values — sourcing real KTC data is a separate,
     not-yet-investigated problem.
  Not deadline-driven the way the pre-draft work was — this is about
  improving accuracy for ongoing dynasty decisions (trades, future
  drafts), not a hard cutoff.

  **Longer-term idea (noted, not started):** `scripts/derive_position_multipliers.py`
  still has to be run by hand and its printed numbers manually copied into
  `POSITION_VALUE_MULTIPLIER`. The easy fix already done is making the
  *season selection* itself current-year-driven (`recent_complete_seasons_weekly_data()`
  looks back from the league's real current season, so it doesn't need
  editing next year). The harder remaining piece — fully automating this
  so it re-derives and applies itself with no manual step at all — is
  deliberately deferred: it would need a decision on *when* to trigger a
  re-derive (season rollover? a scheduled job?) and probably a sanity-check
  guard before auto-applying a new multiplier (e.g. reject a swing beyond
  some threshold vs. the current value), so a bad data pull can't silently
  skew live rankings. Worth a proper look once B (per-player recompute)
  lands, since B may shrink how much this multiplier still matters.

- **Rookie draft dashboard — final verification.** Built and merged (PR #1,
  #2, #3); full writeup in `docs/rookie-draft-big-board.md` and
  `docs/dynasty-draft-web-app.md`. Only remaining before calling it fully
  done: deploy to the Synology NAS (not yet done at all) and use it through
  the actual live draft — see the Synology deploy item under "Pre-draft
  hardening" above for what needs to happen first.

## Future Ideas

- **Trade targets & sells** — given the rebuild strategy, flag which of the
  user's veterans are sellable for picks, and which other teams' picks/young
  players might be realistically available.
- **Roster needs — structural positional weakness, not just week-to-week
  gaps** (user-flagged 2026-07-26, explicitly post-draft). `roster_needs_summary`
  and `roster_weekly_gaps` both answer "do we have enough bodies at this
  position right now/this week" — neither answers "is this position
  structurally weak compared to the rest of the roster (or the league),
  such that it's worth actively shoring up via trade rather than just
  monitoring." Would need a real positional-strength metric (e.g. this
  position's share of total roster value, or its value relative to
  starting-quality replacement level) rather than the current young-core
  headcount heuristic. Natural pairing with the "Trade targets & sells"
  and "League-wide power/timeline read" ideas below - a weak-position
  signal is exactly what should drive who to target in a trade.
- **League-wide power/timeline read** — place every team in the league on a
  rebuild-vs-contend spectrum, to identify good trade partners (contenders who
  overpay for immediate help, rebuilders who overpay for future assets).
- **Free agent / roster-moves evaluator** — a tool for right-now decisions
  outside the draft: which available free agents are worth an add, and which
  current roster players are droppable, given the rebuild timeline. Should
  extend to **in-season pickup monitoring**: when a free agent's situation
  changes materially — signs with a new team, wins a starting job, a
  depth-chart move opens up volume — score their marginal value against the
  current roster the same way the draft plan does (season-average marginal
  starting-lineup value, not raw trade value) and flag it when it would
  actually crack the lineup or clearly outvalue a bench/taxi piece worth
  cutting. This reuses `rank_by_marginal_value`/`recommend_drop` almost as-is
  once free agents are the candidate pool instead of the rookie class — the
  main new inputs are pulling league free agents from Sleeper and some
  signal for "something changed" (a depth-chart delta week over week would
  probably be enough to start; no need for a news/transactions feed on day
  one). Ties into injury-status awareness too, since a starter's injury is
  often exactly what opens the depth-chart move worth reacting to.
- **Broader test coverage** — `tests/test_dynasty_core.py` covers the
  core ranking/lineup logic (see Active, above, for what's in), but
  `sleeper_api.py`/`fantasycalc_api.py` (the retry/session logic itself),
  the CLI's error-handling loop, and most of `dynasty_core.py`'s smaller
  helpers (bye weeks, handcuffs, roster needs) still have none. Worth
  building out once draft-week time pressure is off.
- **Taxi-squad eligibility modeling** — `roster_total_capacity()` assumes
  every candidate is taxi-eligible, true for this draft's rookies but not
  a general accrued-experience eligibility check against Sleeper's actual
  taxi rule. Fold in whenever this needs to handle non-rookie candidates
  (e.g. the free-agent evaluator idea above) rather than as a separate pass.
- **Better logging solution than `print()`** (user-flagged 2026-07-26) —
  `rookie_draft.py`'s CLI output is all `print()` today; `python_guidelines.md`
  calls for the standard `logging` module instead (levels, no `print()` for
  diagnostics). Worth a dedicated look at how much of the CLI's *report*
  output (as opposed to actual diagnostics/warnings, which already use
  `logger` in `dynasty_core.py`/`player_scoring.py`) should even move to
  `logging` versus staying as direct terminal output, since the report is
  the CLI's actual product, not a diagnostic - evaluate in its own feature
  branch rather than folding into unrelated work.

## Context

- Dynasty league (keep all players year to year; rookies only enter via the
  rookie draft).
- User's strategy since year one: accumulate young talent, accept being
  near the bottom of the league short-term, aiming to be competitive within
  ~2-3 years.

### Valuation approach and its remaining gaps

Player/rookie value starts from FantasyCalc's public dynasty rankings
(`fantasycalc_api.py`) — this project has no full valuation model of its
own. FantasyCalc's API only lets us tune for superflex (`numQbs=2`), league
size (`numTeams=12`), and PPR (`ppr=1.0`); it has no parameter for this
league's other non-standard scoring settings, so its raw rankings are a
generic superflex-PPR model, not this league's actual scoring. As of step B,
the correction is applied per-player wherever real NFL history exists (see
`docs/rookie-draft-big-board.md` for the original methodology, and
`player_scoring.py` for the current one):

- ✅ **All of it, per-player** (step B, done) — 6pt passing TDs, this
  league's real `pass_yd` rate, the -3 INT penalty, TE premium,
  `rush_fd`/`rec_fd` first-down bonuses, and `*_40p`/`*_50p` long-play
  bonuses are all corrected for any player with a qualifying real NFL
  season in the last 3 years, via a personalized ratio (see
  `player_scoring.py`) instead of one flat number per position. Rookies
  and low-volume veterans fall back to a position average computed from
  that same pooled sample.
- ⏳ **Still uncertain**: FantasyCalc's own assumed baseline scoring model
  isn't published anywhere, so `player_scoring.BASELINE_SCORING`'s
  standard-scoring assumption (4pt passing TD, -2 INT, standard yardage
  rates, no TE premium/first-down/long-play bonuses) can't be verified
  against FantasyCalc directly — this is the largest remaining source of
  error in the correction, not a specific known scoring category.
- Not a scoring setting, but relevant to roster/pick strategy: taxi squad is
  unusually generous (5 slots, 3 years) vs. typical dynasty leagues — more
  room to stash rookies without a roster crunch.

Ranking itself no longer uses raw (or even corrected) player value directly —
picks are ranked by season-average **marginal starting-lineup value**, which
inherently accounts for positional scarcity without needing a separate
needs-flag override. See `docs/rookie-draft-big-board.md`.

Remaining valuation work (steps A and D) is tracked under the Active
**Valuation algorithm improvements** item, above.
