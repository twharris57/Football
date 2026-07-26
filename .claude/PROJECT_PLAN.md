# Project Plan

Tracks what's actively being worked on, what's queued up next, and longer-range
ideas for this project. When a task is completed, write it up as a design doc
in `docs/` (what was built and why, key decisions) and remove it from this file.

## Active

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
  done: deploy to the Synology NAS and use it through the actual live
  draft.

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
