# Project Plan

Tracks what's actively being worked on, what's queued up next, and longer-range
ideas for this project. When a task is completed, write it up as a design doc
in `docs/` (what was built and why, key decisions) and remove it from this file.

## Active

- **Synology NAS deploy + live-draft verification** (blocks calling the
  dashboard fully done; needed before Sunday 2026-08-02). Everything else
  from the pre-draft hardening review is done — see
  `docs/rookie-draft-big-board.md` and `docs/dynasty-draft-web-app.md` for
  the full methodology/implementation writeup. Needs the user's own action —
  no SSH/credentials to the NAS from here:
  1. Confirm the GHCR build went green on the latest push to `main`
     (`gh run list` / `gh pr checks`).
  2. Deploy on the NAS via `docker-compose.deploy.yml`, verify the running
     container's footer git SHA matches.
  3. Pre-warm the multiplier cache with
     `python scripts/derive_position_multipliers.py` ahead of draft day, not
     live (a cold cache means a 1-2 minute `nfl_data_py` pull on first load).
  4. Use it through the actual live draft. The CLI (`rookie_draft.py`, no
     Docker) remains the safer fallback regardless of how the deploy goes.

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

- **Valuation algorithm improvements** (branch: `feature/valuation-rookie-buckets`)
  — sequenced deliberately, not independent workstreams. E (multiplier data
  pooled across 3 seasons) and B (full per-player scoring recompute) are
  done — see `docs/rookie-draft-big-board.md` for methodology. Remaining:
  1. **A — finer position/play-style multiplier buckets, rescoped to
     rookies only.** Deliberately sequenced after B, not before — a
     veteran-inclusive version of this would mostly be thrown away once B
     replaces the multiplier for anyone with real stats. `import_combine_data`
     (confirmed available) gives real per-rookie athletic profiles — a
     usable classification signal (mobile vs. pocket QB, etc.) without
     needing college stats, which we don't have access to.
  2. **D — blend in KeepTradeCut as a second market source**, time
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
  skew live rankings. Now that B (per-player recompute) has landed, this
  multiplier is a last-resort fallback only — worth a proper look if it
  still seems to matter enough to justify the automation.

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
- **Cap decimal precision in UI displays** (user-flagged 2026-07-26) — value/
  score columns across the CLI and Streamlit tables currently show whatever
  float precision the underlying computation happens to produce; cap display
  to 2 decimal digits with proper rounding (not truncation) everywhere a
  value is rendered for a human, without changing the underlying stored/
  compared precision.

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
