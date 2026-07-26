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
  1. Synology deploy hasn't happened at all yet (not a stale-image problem —
     just not done). `docker-publish.yml` only builds on push to `main`, so
     this branch's per-player scoring work won't exist in any NAS image until
     merged. Before Sunday: merge to `main`, confirm the GHCR build completes,
     deploy to the NAS, and verify the running container's footer git SHA
     matches (check already documented in `docs/dynasty-draft-web-app.md`).
     Pre-warm the cache with one forced refresh ahead of draft day, not live —
     a cold cache means the multi-season `nfl_data_py` pull happens on first
     load. The CLI (`rookie_draft.py`, no Docker) remains the safer fallback
     regardless of how the deploy goes. (Since there's no existing NAS
     deployment, the `players_cache` → `nfl_data_cache` volume rename in
     `docker-compose.deploy.yml` is a non-issue — nothing to orphan.)
  2. Decouple "Force full refresh" from the scoring-multiplier recompute
     (`streamlit_app.py:49` → `dynasty_core.py:987` (players) and `:997-1003`
     (multipliers) → `player_scoring.py:278-300`; re-checked 2026-07-26,
     still current after the same-day league-rule-assumption audit — line
     numbers shifted slightly from the original finding but the issue is
     unchanged). One button currently busts both the Sleeper players cache
     and the multiplier cache, and the latter re-imports 3 seasons of weekly
     + play-by-play data — a 1-2 minute synchronous pull that could freeze
     the app right when the user is on the clock, for data that's static all
     season and never needs a mid-draft recompute. Deferred to a future
     feature branch along with the rest of this list — not fixed here.
  3. Clamp the per-player scoring ratio in `player_scoring.py:264-273` —
     currently `real_points / baseline_points` with no floor/ceiling. A
     qualifying-volume player with a low/negative baseline-points season
     (heavy INTs, low yardage) can produce an extreme ratio that feeds
     `adj_value` -> `season_average_starter_value`, contaminating the
     marginal-value baseline for the whole draft plan. Reject/fall back to
     the position average outside a sane band (e.g. ~[0.5, 2.0]) or below a
     minimum `baseline_points` floor.
  4. Fix the Streamlit cache-key bug in `load_state` (`streamlit_app.py:48-56`)
     — keyed on the raw force-refresh button boolean, not a durable
     `session_state` flag, so the rerun immediately after a force-refresh
     click (e.g. opening an expander) misses cache and silently re-fetches
     both APIs.
  5. Verify `bye_week_by_team(2026)` (`dynasty_core.py:396-413`) returns all
     32 teams before draft day — it silently drops any team that doesn't
     resolve to exactly one missing week, understating value everywhere
     downstream with no visible symptom.

  **Worth doing this season (not blocking Sunday):**
  - Catch `ValueError`/`TypeError` from a bad league_id or typo'd username in
    `rookie_draft.py`'s refresh loop (only `requests.RequestException` is
    caught today; Streamlit already handles this).
  - Surface a UI warning when byes/handcuffs silently fall back to `{}` on
    fetch failure (`dynasty_core.py:993-1002`) — currently indistinguishable
    from "no conflicts found."
  - Add caching/TTL to `fantasycalc_api.get_dynasty_values` — currently
    uncached, so even a plain "Refresh" click re-hits it, contradicting the
    "Refresh is cheap" framing.
  - Cache `bye_week_by_team`/`handcuff_map` per session instead of refetching
    from `nfl_data_py` on every refresh click, not just force-refresh.
  - Add an end-to-end test for `multi_round_plan` (`dynasty_core.py:785-928`)
    — the actual "what to pick" output has zero direct test coverage today,
    even though its sub-pieces (`assign_starters`, drop logic) are tested.
  - Collapse the Draft Plan tab's methodology caption into a closed
    `st.expander` — currently pushes the plan table below the fold on a
    phone, on every refresh.
  - Visually distinguish `status=completed` vs. `status=upcoming` rows in the
    plan table (color/style, not just text) — a fast scroll under draft-day
    pressure could conflate a guaranteed pick with a simulated one.
  - Confirm the league's real `scoring_settings` has no per-game yardage
    bonuses (`bonus_pass_yd_300` etc.) that `_stat_points` doesn't check for
    — likely moot, worth a one-time dump to confirm.

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

- **Draft dashboard UX polish & minor fixes** — user-flagged during review of
  PR #5 (2026-07-26), across the Streamlit dashboard's Draft Plan/Lineup/Draft
  Board/Your Roster tabs. Not blocking, not sequenced yet — pick these up in
  whatever order makes sense once started.
  1. ✅ **"Backup options" folded into per-pick sections, not a separate
     table.** Resolved together with item 2, below, once the round table
     became one collapsible section per pick — each pick's own backup
     options (if any) now render inside its own expanded view, so a
     separate consolidated table would have been redundant.
  2. ✅ **Round table restructured into per-pick collapsible sections.**
     `streamlit_app.py`'s Draft Plan tab is now one `st.expander` per pick
     instead of one flat table. Design specifics confirmed with the user:
     collapsed view shows pick + drop + marginal value (e.g. "🔜 Round 1,
     pick 2: DRAFT Jeremiyah Love (RB) · DROP Jordan Whittington (WR) ·
     +5732"); ✅/🔜 icon distinguishes a completed (real) pick from an
     upcoming (simulated) one; a ⚠️ suffix flags a suggested drop that's a
     current starter. Expanded view holds the full reasoning text and any
     backup options table.
  3. ✅ **Lineup tab now has IR and Taxi sections.** `lineup_breakdown()`
     returns (starters, bench, taxi, ir), cross-referencing
     `roster["taxi"]`/`roster["reserve"]` instead of lumping both into
     "bench". Found and fixed a real bug along the way: `roster_capacity()`
     claimed reserve/IR "isn't reliably derivable from the Sleeper API" —
     false, verified directly (`roster["reserve"]` is a plain player_id
     list, same shape as `roster["taxi"]`, populated for several other
     rosters in the league). It was previously omitted from
     `active_filled`'s subtraction, so any roster with IR players had its
     active-roster capacity *overstated* (fewer open slots shown than
     actually available) — fixed, with a regression test.
     `roster_total_capacity()` still excludes reserve/IR on purpose (it's
     for an already-rostered injured player, not room for a new one).
  4. ✅ **`handcuff_to` is always empty on the rookie big board — root cause
     found, not a code bug.** Verified directly: of this draft's 227 rookies,
     only 11 have a `gsis_id`/`sleeper_id` mapping in `nfl.import_ids()` at
     all, and only 2 of those 11 appear anywhere in the real RB depth chart
     (both as backups, not starters). `handcuff_map()`'s join
     (`dynasty_core.py:500-501`) is correct — `nfl_data_py`'s ID crosswalk
     itself simply hasn't caught up with this year's incoming class yet, the
     same kind of data-publication lag already documented elsewhere in this
     project (e.g. `recent_complete_seasons_weekly_data`'s season lookback).
     Added a caption in the Streamlit big board (`streamlit_app.py`) and a
     note in `docs/rookie-draft-big-board.md` explaining why `handcuff_to`
     will be sparse for rookies pre-season, so it doesn't read as broken.
     Should fill in naturally as the crosswalk updates later in the year —
     nothing to fix in code.
  5. ✅ **Roster Value's "aging" cutoff now accounts for position.**
     `LOW_VALUE_AGING_AGE` (`dynasty_core.py`) was one flat `27` for every
     position; now a per-position dict (`RB: 27, WR: 29, TE: 30, QB: 33`,
     with a `DEFAULT_LOW_VALUE_AGING_AGE = 29` fallback) — judgment calls,
     not derived from any league rule, revisit by feel like the other
     rebuild-strategy heuristics. **Not done, left for later:** pulling more
     per-player detail from Sleeper's player feed over time — currently only
     name/position/team/age/college/years_exp are read, and
     `sleeper_api.get_players()` returns much more per player that isn't
     surfaced anywhere yet.
  6. ✅ **Bye Week Conflicts now shows real lineup-strength impact, not just
     who's out.** `roster_bye_conflicts` used to only flag which players at a
     position share a bye; now one row per week with an active-roster player
     out, showing `players_out`, `fillers` (who steps into the starting
     lineup as a result), and `lineup_delta` (that week's optimal starting
     value vs. a full-strength week) — reusing the same per-week
     `assign_starters` machinery as `season_average_starter_value`. A -500
     week and a -5000 week now read very differently, as intended.
     Streamlit presentation (added same session, user follow-up): also
     restructured into one collapsible section per week, same pattern as
     item 2's round table — collapsed shows out/fillers/delta, expanded adds
     a plain-language breakdown. ✅/📅 distinguishes a week that's already
     happened from one still ahead, using `league["settings"]["leg"]`
     (Sleeper's current-week counter — not used anywhere else in this
     project yet) — a week already past still shows this same roster-based
     projection, not a real result, since there's no live in-week stats feed
     yet; the UI says so explicitly rather than implying otherwise.

     **New finding while building this, not fixed here:** `lineup_breakdown`,
     `season_average_starter_value`, and `rank_by_marginal_value` all feed
     `assign_starters` the *entire* `roster["players"]` list, including taxi
     and IR/reserve players — none of whom Sleeper actually allows into the
     starting lineup. The new bye-week code above correctly excludes them
     (see its docstring), but the older functions don't, so a high-value
     taxi/IR player could theoretically get "assigned" as an optimal
     starter in those paths — hasn't visibly surfaced yet (their values
     happen to be lower than the real bench today) but is a latent
     correctness gap, not just a style inconsistency with the new code.
     Worth fixing in all three, consistently, as its own task rather than
     folded into this one — meaningfully broader blast radius than the bye-
     week feature that surfaced it.

- **Valuation algorithm improvements** (branch: `feature/valuation-improvements`)
  — sequenced deliberately, not independent workstreams:
  1. ✅ **E — refresh the QB/TE multiplier's data basis.** Was derived from
     2024 only (39 qualifying QBs, 45 TEs — a fairly small, single-season
     sample); now pooled across the 3 most recent complete seasons (108
     QB player-seasons, 135 TE, via `scripts/derive_position_multipliers.py`
     + `recent_complete_seasons_weekly_data()`). Stays useful regardless of
     how B turns out, since rookies will always need this fallback (see
     step 2).
  2. ✅ **B — full per-player scoring recompute for players with real NFL
     history.** Replaced the position-level multiplier with a per-player
     one (see `player_scoring.py`): for anyone with a qualifying season in
     the last 3 years (same volume bars as E, extended to RB ≥100 carries
     / WR ≥50 targets), this league's exact `scoring_settings` is applied
     to raw weekly stats — 6pt passing TDs, this league's real (non-
     standard) `pass_yd` rate, the -3 INT penalty (a previously-undocumented
     gap — the assumed baseline is -2), TE premium, `rush_fd`/`rec_fd`
     first-down bonuses, and long-play bonuses (`*_40p`/`*_50p`, pulled from
     play-by-play data since weekly aggregates don't preserve play length)
     — against FantasyCalc's assumed baseline model (an explicit, documented
     assumption in `player_scoring.BASELINE_SCORING`, since FantasyCalc
     doesn't publish its own formula: standard 4pt passing TD, -2 INT, full
     PPR, 6pt rush/rec TD, no TE premium, no first-down/long-play bonuses —
     **the biggest remaining source of uncertainty in this whole
     correction**, since it can't be verified against FantasyCalc directly).
     Below the qualifying bar (or for rookies, with no NFL history at all),
     falls back to a position average computed from that same pooled
     sample — `POSITION_VALUE_MULTIPLIER`'s hardcoded QB/TE values are now
     a last-resort fallback only, used if this whole enrichment fails.
     **Resolved the open blending question** by not introducing a second
     value scale at all: every ranking function already reads FantasyCalc's
     value through one function (`fc_value_by_sleeper_id`), which now bakes
     the per-player (or position-average) multiplier into `adj_value`
     directly — rookies and veterans stay on the same unit everywhere.
     Cached to disk (`.cache/scoring_multipliers.json`, no TTL — the
     underlying seasons are historical/complete and don't change on a
     clock) and tied to the existing "force full refresh" action: a plain
     refresh reuses the cache, force-refresh recomputes from scratch.
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
