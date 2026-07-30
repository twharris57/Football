# Project Plan

Grouped by theme; within each group, items are ordered by priority (most
important first). When a task is completed, write it up as a design doc in
`docs/` (what was built and why, key decisions) and remove it from this list.
Durable background (league identity, rebuild strategy, valuation methodology)
lives in `CLAUDE.md` and `docs/`, not here — this file is only what's left to do.

## Now — blocking

1. [ ] **Synology NAS deploy + live-draft verification** — blocks calling the
   dashboard fully done. Everything else from the pre-draft hardening review
   is done — see `docs/rookie-draft-big-board.md` and
   `docs/dynasty-draft-web-app.md` for the full methodology/implementation
   writeup. Needs the user's own action — no SSH/credentials to the NAS from
   here:
   1. Confirm the GHCR build went green on the latest push to `main`
      (`gh run list` / `gh pr checks`).
   2. Deploy on the NAS via `docker-compose.deploy.yml`, verify the running
      container's footer git SHA matches.
   3. Pre-warm the multiplier cache with
      `python scripts/derive_position_multipliers.py` ahead of draft day, not
      live (a cold cache means a 1-2 minute `nfl_data_py` pull on first load).
   4. Use it through the actual live draft. The CLI (`rookie_draft.py`, no
      Docker) remains the safer fallback regardless of how the deploy goes.

## Valuation & data accuracy

Not deadline-driven the way draft-week readiness is — this is about improving
accuracy for ongoing dynasty decisions (trades, future drafts), not a hard
cutoff. E (multiplier data pooled across 3 seasons), B (full per-player
scoring recompute), and A (finer position/play-style multiplier buckets,
rescoped to rookies only) are done — see `docs/rookie-draft-big-board.md` for
methodology.

1. [ ] **D — blend in KeepTradeCut as a second market source**, time
   permitting. `import_ids()` only gives a `ktc_id` crosswalk column, not
   actual KTC values — sourcing real KTC data is a separate,
   not-yet-investigated problem.
2. [ ] **Automate `scripts/derive_position_multipliers.py` re-derivation.**
   It still has to be run by hand and its printed numbers manually copied
   into `POSITION_VALUE_MULTIPLIER`. The easy fix already done is making the
   *season selection* itself current-year-driven
   (`recent_complete_seasons_weekly_data()` looks back from the league's real
   current season, so it doesn't need editing next year). The harder
   remaining piece — fully automating this so it re-derives and applies
   itself with no manual step at all — is deliberately deferred: it would
   need a decision on *when* to trigger a re-derive (season rollover? a
   scheduled job?) and probably a sanity-check guard before auto-applying a
   new multiplier (e.g. reject a swing beyond some threshold vs. the current
   value), so a bad data pull can't silently skew live rankings. Now that B
   (per-player recompute) has landed, this multiplier is a last-resort
   fallback only — worth a proper look if it still seems to matter enough to
   justify the automation.

## Post-draft roster & trade tooling

Explicitly post-draft (user-flagged 2026-07-26). Ordered so the foundational
signal (item 1) lands before the tools that consume it (items 3-4).

1. [ ] **Roster needs — structural positional weakness, not just
   week-to-week gaps.** `roster_needs_summary` and `roster_weekly_gaps` both
   answer "do we have enough bodies at this position right now/this week" —
   neither answers "is this position structurally weak compared to the rest
   of the roster (or the league), such that it's worth actively shoring up
   via trade rather than just monitoring." Would need a real
   positional-strength metric (e.g. this position's share of total roster
   value, or its value relative to starting-quality replacement level)
   rather than the current young-core headcount heuristic. A weak-position
   signal from this is exactly what should drive who to target in a trade —
   feeds items 3 and 4 below.
2. [ ] **Free agent / roster-moves evaluator** — a tool for right-now
   decisions outside the draft: which available free agents are worth an
   add, and which current roster players are droppable, given the rebuild
   timeline. Should extend to **in-season pickup monitoring**: when a free
   agent's situation changes materially — signs with a new team, wins a
   starting job, a depth-chart move opens up volume — score their marginal
   value against the current roster the same way the draft plan does
   (season-average marginal starting-lineup value, not raw trade value) and
   flag it when it would actually crack the lineup or clearly outvalue a
   bench/taxi piece worth cutting. This reuses `rank_by_marginal_value`/
   `recommend_drop` almost as-is once free agents are the candidate pool
   instead of the rookie class — the main new inputs are pulling league free
   agents from Sleeper and some signal for "something changed" (a
   depth-chart delta week over week would probably be enough to start; no
   news/transactions feed needed on day one). Ties into injury-status
   awareness too, since a starter's injury is often exactly what opens the
   depth-chart move worth reacting to. Needs **taxi-squad eligibility
   modeling** first (or alongside): `roster_total_capacity()` currently
   assumes every candidate is taxi-eligible, true for rookies but not a
   general accrued-experience eligibility check against Sleeper's actual
   taxi rule — free agents won't all qualify.
3. [ ] **Trade targets & sells** — given the rebuild strategy, flag which of
   the user's veterans are sellable for picks, and which other teams'
   picks/young players might be realistically available. Depends on item 1's
   weak-position signal to know who to target.
4. [ ] **League-wide power/timeline read** — place every team in the league
   on a rebuild-vs-contend spectrum, to identify good trade partners
   (contenders who overpay for immediate help, rebuilders who overpay for
   future assets). Pairs with item 3.
5. [ ] **League tab — all-teams summary view** (user-flagged 2026-07-29,
   longer term). A compact row per team (total roster value, biggest need,
   capacity) to scan the whole league at a glance before drilling into one
   team, complementing the Your Roster tab's team selector (added
   2026-07-29), which only ever shows one team at a time. Cheaper than it
   would have been before that selector shipped —
   `dynasty_core.team_roster_analysis()` already runs this exact per-team
   analysis for any roster on demand; this is "call it for all ~12 teams
   and lay out a summary row," not new analysis logic. A natural
   lighter-weight precursor to item 4's power/timeline read, not a
   replacement for it — this surfaces raw stats per team, not a
   rebuild-vs-contend classification.

## Code quality, tests & UX polish

1. [ ] **Broader test coverage.** `tests/test_dynasty_core.py` and
   `tests/test_player_scoring.py` cover the core ranking/lineup/valuation
   logic, but `sleeper_api.py`/`fantasycalc_api.py` (the retry/session logic
   and cache-TTL behavior itself) and the CLI's error-handling loop still
   have none. Worth building out now that draft-week time pressure is off.
2. [ ] **Cap decimal precision in UI displays** (user-flagged 2026-07-26) —
   value/score columns across the CLI and Streamlit tables currently show
   whatever float precision the underlying computation happens to produce;
   cap display to 2 decimal digits with proper rounding (not truncation)
   everywhere a value is rendered for a human, without changing the
   underlying stored/compared precision.
3. [ ] **Better logging solution than `print()`** (user-flagged 2026-07-26) —
   `rookie_draft.py`'s CLI output is all `print()` today; `python_guidelines.md`
   calls for the standard `logging` module instead (levels, no `print()` for
   diagnostics). Worth a dedicated look at how much of the CLI's *report*
   output (as opposed to actual diagnostics/warnings, which already use
   `logger` in `dynasty_core.py`/`player_scoring.py`) should even move to
   `logging` versus staying as direct terminal output, since the report is
   the CLI's actual product, not a diagnostic — evaluate in its own feature
   branch rather than folding into unrelated work.
4. [ ] **Dedupe/log on `gsis_id` collisions** in the ID-crosswalk join
   (`player_scoring.py:417-418`, `dynasty_core.py:686-687`) — both build a
   `{gsis_id: sleeper_id}` dict via a plain dict comprehension, which
   silently keeps only the last row on a collision instead of flagging one.
5. [ ] **Split the generic "Couldn't reach Sleeper/FantasyCalc" error
   message** to name which service actually failed.

## Deferred / low priority

Judged not worth the time right now; revisit only if the underlying
assumption changes.

1. [ ] **Handcuff proxy false-positive risk** — depth-chart rank 2 has real
   false-positive risk in modern RB committees. Informational field only,
   not worth revisiting.
2. [ ] **Exclude a candidate from its own drop-simulation** in
   `recommend_drop` — theoretically possible, vanishingly unlikely to
   surface as a top pick.
