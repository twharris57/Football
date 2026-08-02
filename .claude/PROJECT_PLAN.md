# Project Plan

Grouped by theme; within each group, items are ordered by priority (most
important first). When a task is completed, write it up as a design doc in
`docs/` (what was built and why, key decisions) and remove it from this list.
Durable background (league identity, rebuild strategy, valuation methodology)
lives in `CLAUDE.md` and `docs/`, not here — this file is only what's left to do.

**Item IDs**: every open item carries a permanent `<SECTION>-<n>` tag in its
own heading (`NB` = Now — blocking, `RT` = Roster & trade tooling, `VA` =
Valuation & data accuracy, `CQ` = Code quality/tests/UX, `DL` = Deferred/low
priority) — e.g. `RT-3`. Assigned once, in document order, and never reused
or renumbered, even after the item it names is completed and removed —
matching how `VA`'s items were already informally lettered A-E before this
convention was written down (`A`/`B`/`E` are done and gone; `D` survives as
`VA-1`). Cross-reference other items by this tag (`see RT-3`), never by list
position (`item 2`) — a positional reference silently points at the wrong
item the moment anything above it is inserted, reordered, or removed. A new
item gets the next unused number for its section's prefix, appended wherever
priority order actually puts it in the list — position and ID are
independent. The ephemeral "Current branch — fix before merge" section is
exempt (cleared on every merge, so nothing outlives it to cross-reference).

## Current branch — fix before merge

Findings from reviewing the *active* branch's own not-yet-merged work —
kept separate from the thematic backlog below so "fix this before the PR
merges" is never mixed in with "someday" work. Ephemeral by design: cleared
out when the branch merges, not carried forward as history (the merged PR's
description is the historical record). A finding that gets explicitly
deferred rather than fixed moves down into the appropriate thematic section
below as a normal backlog item, same as any other deferred work.

**`feature/trade-block-monitoring` (PR #23, reviewed 2026-08-02):**

1. **`evaluate_trade()`'s `over_capacity` misfires for any roster already
   carrying taxi-squad players — the norm for this league, not an edge
   case.** `roster_total_capacity(..., taxi_eligible=False)` zeroes
   `taxi_slots` out of the ceiling entirely, but `roster.get("players")`
   (what `evaluate_trade` measures `roster_size_after` against) includes
   *existing* taxi occupants alongside the active/bench group —
   `lineup_breakdown`'s own docstring confirms this: "Taxi and IR/reserve
   players are in `roster["players"]` alongside the real bench." So a team
   stashing even one taxi rookie (this league's whole rebuild strategy per
   `CLAUDE.md`) can already exceed `len(roster_positions) + reserve_filled`
   before the trade changes anything — `over_capacity` can fire, warning
   "an additional cut would be needed," on a plain 1-for-1 swap that needs
   no cut at all. `free_agent_board()` has the identical root cause (see
   new `RT-11` below) — not a new bug there, just never surfaced as a
   literal user-facing capacity claim the way this tab now states it. No
   test (here or in the pre-existing `TestFreeAgentBoard`) constructs a
   roster with a non-empty `taxi` list, so `TestEvaluateTrade` couldn't
   have caught it either.
   Real fix belongs in the shared `roster_total_capacity()` helper: give it
   a `taxi_filled` parameter (credited whenever `taxi_eligible=False`,
   mirroring how `reserve_filled` already works) instead of zeroing taxi
   capacity outright — fixes `evaluate_trade` and `free_agent_board` in the
   same change. See `.claude/conventions/valuation_principles.md`'s new
   "capacity ceiling" rule for the general shape of this mistake.
   Smaller, same-shaped nuance worth folding into the same fix pass:
   `evaluate_trade`'s `reserve_filled` is read from the *pre*-trade roster;
   if `outgoing_player_ids` includes a player currently on IR/reserve, the
   real post-trade capacity should shrink by one to match, which the
   current call doesn't reflect. Much smaller blast radius (off-by-one,
   only when an IR player is one of the traded assets) than the taxi issue
   above, but worth closing in the same pass rather than leaving a second
   latent gap next to the one just found.

## Now — blocking

1. [ ] **NB-1: Synology NAS deploy + live-draft verification** — blocks calling the
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

## Roster & trade tooling

Originally scoped as explicitly post-draft (user-flagged 2026-07-26), then
briefly reordered 2026-07-30 to put trade targets & sells first given real
trade talk already happening pre-draft, then reordered again same day: the
user judged that shipping trade targets & sells before the positional-value
and team-power foundations it needs would produce a weak tool that has to
be redone once those land, so the foundations come first. Still bumped
ahead of Valuation & data accuracy below, which remains explicitly not
deadline-driven.

**Positional-value foundation (VOR/replacement-level, SUPER_FLEX-aware QB
demand), the league-wide power/timeline read (`power_score`, split into
independent `quality_score`/`timeline_score` axes), and small-sample
shrinkage on that read's `win_pct` are done** — see
`docs/rookie-draft-big-board.md`'s "Roster needs" and "Team timeline /
power-timeline read" sections for the full methodology.

**Trade targets & sells v1 (`sellable_players()`, `pick_trade_values()`) is
done** — see `docs/rookie-draft-big-board.md`'s "Trade targets & sells"
section for the full methodology.

Deliberately out of v1, not forgotten:
- **Selling starters, not just depth** — the "sellable vs. just
  droppable" line for a position's own top-value players (not bench
  surplus) is a much bigger strategic call (trade away a good win-now
  asset for future value, core to a rebuild) than "there's unused depth
  here." Left for a human to judge directly against a specific offer,
  not modeled.
- **Draft-pick ownership beyond next season** — Sleeper's `traded_picks`
  has no fixed "how many years out" window, only entries for picks
  actually traded (`FUTURE_PICK_YEARS_AHEAD = 1` in `dynasty_core.py`).
  Extending further is possible but was scoped out to avoid listing
  picks with zero real trade activity that far out.
- **Young non-rookie depth isn't protected the way `LOW_VALUE_YOUNG_AGE`
  protects it elsewhere** (assistant valuation review, 2026-08-01) —
  `sellable_players` excludes true rookies (`years_exp` falsy) but nothing
  younger than that; a promising 2nd-year breakout at a surplus position
  can show up as "sellable" even though `roster_value_analysis` elsewhere
  in this same rebuild-strategy codebase explicitly treats "low-value but
  young" as hold-not-sell, not drop-or-sell. Not necessarily wrong, given
  this list is explicitly framed as candidates for a human to judge
  against a specific offer, not a recommendation — but worth a deliberate
  decision (extend the exclusion, or leave it and rely on the human)
  rather than an unexamined inconsistency between the two features.

**Free agent / roster-moves evaluator v1 (`free_agent_board()`) is done** —
see `docs/rookie-draft-big-board.md`'s "Free agents" section for the full
methodology. Ranks every available (non-rostered) player by marginal value
against a roster, reusing `rank_by_marginal_value` exactly like the draft
plan does; active-roster-only capacity (`taxi_eligible=False` — Sleeper's
real accrued-experience taxi rule isn't modeled, see `RT-8` below);
remaining FAAB shown for context, no bid-sizing (see `RT-10` below); no
in-season change monitoring, recomputed fresh every refresh instead (see
`RT-9` below).

**Trade evaluator (`evaluate_trade()`) is done** — see
`docs/rookie-draft-big-board.md`'s "Trade evaluator" section for the full
methodology. Reframed from the originally-scoped "watch the trade block"
(user feedback, 2026-08-02): real trade offers are two-sided and often
multi-asset (players and/or picks on either side), so this evaluates an
arbitrary proposed trade between two selected teams — season-average
marginal lineup value plus a market-value (`adj_value`/pick `value`) read,
shown for both sides — reusing `season_average_starter_value` and
`pick_trade_values` rather than a new valuation model. 3-way trades aren't
supported (rare, disproportionate complexity). Manual/on-demand, no trade
feed (Sleeper doesn't expose trade discussions) — see `RT-6` below for the
contextual-research idea this could still feed into.

1. [ ] **RT-4: Make "need"/strategy phase-aware — a static rule today, should
   evolve by rebuild year** (user-flagged 2026-07-29, longer term). Right
   now `roster_needs_summary`'s `need` flag is one fixed rule for all
   time (fewer than `YOUNG_CORE_NEED_THRESHOLD` players at a position with
   `<= YOUNG_CORE_MAX_YOE` years of experience), and the rebuild strategy
   described in `CLAUDE.md` ("accumulate young talent... competitive
   within ~2-3 years") is a static description, not something the code
   actually tracks a position in. The user's stated framework: year 1 was
   about accumulating rookies (this project's whole existing purpose);
   year 2 should shift toward smart trades, continuing to find promising
   talent opportunistically — not just rookies, but free agents with a
   sudden uptick in opportunity/fortune (this is exactly RT-9's
   in-season pickup monitoring, once that lands) — and dropping deadweight with limited
   future payoff (already partly modeled by `roster_value_analysis`'s
   `LOW_VALUE_AGING_AGE` cutoff, but not tied to a rebuild-year concept
   either). Would need an explicit "what phase of the rebuild are we in"
   input (probably just a manually-set year/phase, not inferred) that
   shifts behavior across `need`, drop-candidate, and free-agent-flagging
   logic, rather than one flat rule doing double duty for every year.
   Related to but distinct from the positional-value work above — that's
   about *which position* is weak; this is about *what kind of move* the
   team should even be looking for at this point in the rebuild.
2. [ ] **RT-5: League tab — all-teams summary view** (user-flagged 2026-07-29,
   longer term). A compact row per team (total roster value, biggest need,
   capacity) to scan the whole league at a glance before drilling into one
   team, complementing the Roster tab's team selector (added
   2026-07-29), which only ever shows one team at a time. Cheaper than it
   would have been before that selector shipped —
   `dynasty_core.team_roster_analysis()` already runs this exact per-team
   analysis for any roster on demand; this is "call it for all ~12 teams
   and lay out a summary row," not new analysis logic. A natural
   lighter-weight complement to the power/timeline read above (done
   2026-08-01) — this surfaces raw stats per team, not a rebuild-vs-contend
   classification, but both answer "what does this team look like" at a
   glance.
3. [ ] **RT-6: Contextual research check for news/hype beyond Sleeper's data**
   (user-flagged 2026-07-31, possibly via "Claude Scout" or similar — name
   unconfirmed) — a rare, explicitly user-triggered lookup (not a
   background job) for one *specific* named player: pull recent context an
   LLM-with-web-access can surface that Sleeper/FantasyCalc don't carry
   directly — real trade buzz, a beat-reporter note on a depth-chart
   change, injury detail beyond Sleeper's status field — to sit alongside,
   not replace, the stats-based `adj_value`/marginal-value numbers.
   Directly addresses a limitation named in the 2026-07-31 valuation
   review: the whole pipeline is market-value-plus-scoring-correction, so
   it has no way to react to a hype cycle or a fresh injury faster than
   FantasyCalc's own market already has. Needs investigating what's
   actually available and appropriate here before committing to an
   implementation — treat the specific tool name as unverified, just the
   user's working label for the idea. Natural entry points: RT-2's
   trade evaluator (checking one flagged trade idea) and RT-3's
   free-agent evaluator (checking one waiver target) — not a general
   always-on feed, and not a replacement for the stats-based ranking
   anywhere in the pipeline.
4. [ ] **RT-7: Use `points_for`/point differential as a steadier alternative
   to win/loss in the power/timeline read** (deferred from the small-sample
   shrinkage work above, 2026-08-02) — shrinkage toward `0.5` (done, see
   above) addresses the small-sample variance problem directly, but binary
   win/loss is still a noisier signal than point differential even at a
   full sample size, standard practice in sabermetric-style team-strength
   reads. Not picked up alongside the shrinkage fix because it's a bigger
   scope: `sleeper_api.py` has never pulled or verified Sleeper's
   points-for field (name, decimal-split format — Sleeper's own API splits
   `fpts` into a whole-number and a `_decimal` field for other objects, so
   the roster `settings` shape needs checking directly, not assumed), and
   it needs a real design decision on how to blend/weight it against (or
   replace) `win_pct` rather than just swapping the input.
5. [ ] **RT-8: Model real taxi-squad eligibility for free-agent adds**
   (deferred from the free-agent evaluator v1 above, 2026-08-02) —
   `free_agent_board()` currently passes `taxi_eligible=False` to
   `roster_total_capacity()`/`rank_by_marginal_value()`, so an add is only
   ever suggested for an open active roster slot or via a drop, never an
   open taxi slot — correct for rookies (always taxi-eligible, the draft
   plan's own default) but overly conservative for veteran free agents who
   might genuinely qualify under Sleeper's real accrued-experience taxi
   rule. Needs that rule verified live (field name, exact threshold) before
   modeling it — not guessed at, per this project's "document what you
   can't verify" pattern. The `taxi_eligible` flag already threads through
   both functions; this is "verify the real rule and flip candidates that
   qualify to `taxi_eligible=True` on a per-candidate basis," not a
   rearchitecture. See `RT-11` below for a sharper, higher-severity version
   of this same simplification's cost, found while reviewing the trade
   evaluator.
6. [ ] **RT-9: In-season "something changed" pickup monitoring**
   (deferred from the free-agent evaluator v1 above, 2026-08-02) —
   `free_agent_board()` is a real-time snapshot, recomputed fresh every
   refresh like every other feature here, not an alerting system. Actually
   flagging when a free agent's situation changes materially (signs with a
   new team, wins a starting job, a depth-chart move opens up volume)
   needs some week-over-week delta signal this project has nowhere to
   store — `CLAUDE.md`: "everything is pulled fresh... each run," no
   persistence layer anywhere. A depth-chart delta would probably be
   enough to start (no news/transactions feed needed on day one), but it's
   a real architecture addition (state that survives between refreshes),
   not a v1-scope change. Referenced by `RT-4`'s phase-aware rebuild-year
   work, which assumed this would ship alongside the free-agent evaluator.
   `RT-2` (the trade evaluator, reframed as an on-demand two-sided/multi-asset
   check rather than a monitor) no longer depends on this.
7. [ ] **RT-10: FAAB bid-threshold modeling** (deferred from the free-agent
   evaluator v1 above, 2026-08-02) — `free_agent_board()` shows remaining
   FAAB (`league["settings"]["waiver_budget"] - roster["settings"].
   waiver_budget_used`, both already pulled, no new fetch) purely as
   context; there's no bid-amount input anywhere in this app for a
   threshold to apply to yet. A reasonable v1 of this specific piece:
   flag when a recommended pickup wouldn't crack the starting lineup *and*
   the user is about to spend a large share of remaining budget on it —
   once there's a real bid-amount input to check that against — rather
   than the full opportunity-cost modeling ("spend now vs. save for a
   bigger add later") that's a genuine optimal-stopping problem with no
   clean closed-form answer.
8. [ ] **RT-11: `free_agent_board()`'s `taxi_eligible=False` capacity check
   shares the root cause found in the trade evaluator's fix-before-merge
   review** (assistant valuation review, 2026-08-02) — `RT-8` above frames
   `taxi_eligible=False` as merely "overly conservative" (a new candidate
   can't use an *open* taxi slot). The sharper version: `roster_total_capacity(...,
   taxi_eligible=False)` also strips capacity credit for taxi slots a team
   *already* has filled, since `roster.get("players")` (what
   `rank_by_marginal_value` measures roster size against) includes existing
   taxi occupants alongside the active/bench group. A team stashing any
   taxi player — the norm here, given this league's rebuild strategy — can
   read as needing a forced drop for nearly every free-agent candidate even
   with genuine open bench room. Same fix as the trade evaluator's: give
   `roster_total_capacity()` a `taxi_filled` parameter, credited whenever
   `taxi_eligible=False`, instead of zeroing taxi capacity outright. Fix
   alongside `RT-8`'s real-eligibility modeling in the same pass — both
   touch the same call sites and the same underlying helper.

## Valuation & data accuracy

Not deadline-driven the way the group above now is (see 2026-07-30 note) —
this is about improving accuracy for ongoing dynasty decisions, not a hard
cutoff. E (multiplier data pooled across 3 seasons), B (full per-player
scoring recompute), and A (finer position/play-style multiplier buckets,
rescoped to rookies only) are done — see `docs/rookie-draft-big-board.md` for
methodology.

1. [ ] **VA-1 (formerly "D"): blend in KeepTradeCut as a second market source**, time
   permitting. `import_ids()` only gives a `ktc_id` crosswalk column, not
   actual KTC values — sourcing real KTC data is a separate,
   not-yet-investigated problem.

   **Extra motivation, not just a nice-to-have** (assistant valuation
   review, 2026-07-31): KTC publishes separate superflex-specific
   rankings, which could serve as a rough external cross-check on whether
   this project's own VOR/replacement-level signal still under-credits QB
   after the SUPER_FLEX/QB fix (Roster & trade tooling, done 2026-08-01) —
   not a substitute for that fix, which already landed, but a useful
   independent sanity check on how well-calibrated it turned out once KTC
   data exists to compare against.
2. [ ] **VA-2: Derive `BASELINE_SCORING`'s `rec` value from the real `ppr` param
   instead of hardcoding `1.0`** (assistant valuation review, 2026-07-31) —
   `get_dynasty_values()` already sends this league's actual PPR
   (`league["scoring_settings"]["rec"]`) to FantasyCalc, so its returned
   market `value` is already calibrated to it. But `player_scoring.
   BASELINE_SCORING` hardcodes `"rec": 1.0` as "FantasyCalc's assumed
   baseline" regardless of what `ppr` was actually sent. Currently
   harmless — this league is full PPR, so `1.0` happens to be correct —
   but if the league's PPR setting is ever changed to anything else, the
   per-player correction ratio would silently start conflating the
   intended residual scoring-format delta with an unintended PPR delta
   that FantasyCalc's own API call already priced in. Cheap fix once
   picked up: thread the real `ppr` value into `BASELINE_SCORING`'s `rec`
   key instead of the literal `1.0`. Not urgent while the league stays
   full PPR — flagged in `docs/rookie-draft-big-board.md`'s "Static
   assumptions" table in the meantime so it isn't a silent trap.
3. [ ] **VA-3: Automate `scripts/derive_position_multipliers.py` re-derivation.**
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
4. [ ] **VA-4: Post-draft valuation retrospective** (assistant valuation review,
   2026-07-31) — once the live draft itself is done and there's no
   time-pressure to protect, revisit a few statistically-motivated
   refinements that are real improvements but not worth the added
   complexity mid-draft:
   - **Shrinkage instead of a hard `QUALIFYING_VOLUME` cutoff.** A player
     just below the volume bar gets 0% weight on their own signal; a
     player just above it gets 100% — a discontinuity. An empirical-Bayes/
     shrinkage blend toward the position average, weighted by sample size,
     would be smoother and more defensible, at real added complexity cost
     for a personal tool.
   - **Continuous rookie play-style scoring instead of a binary
     median-split bucket.** `_derive_rookie_buckets()` currently splits
     each position into exactly two buckets off one metric (e.g. QB 40-yd
     dash). A regression-based continuous score over multiple combine
     metrics would resolve more nuance than a single median split can.
   - **Document (done) and, if it ever looks systematically off, revisit
     the linearity assumption in `adj_value = value * multiplier`.**
     Applying a points-derived ratio multiplicatively to a market value
     assumes value scales linearly with points under the counterfactual
     scoring rule — a reasonable first-order approximation, but real
     dynasty value is plausibly convex near the top of a position and
     flatter near replacement. Caveat added to `docs/rookie-draft-big-board.md`
     as part of this review.

   **If college stats are ever pulled in** (user-flagged 2026-07-31) — the
   shrinkage and continuous-bucketing refinements above are exactly where
   that data would earn its keep: college target share, yards per route
   run, and draft capital are all more predictive of rookie fantasy
   outcomes than combine testing alone, and would slot into the same
   `_derive_rookie_buckets`/multiplier machinery as additional features
   rather than requiring a new pipeline.

5. [ ] **VA-5: `win_pct` doesn't credit a tie as half a win** (assistant
   valuation review, 2026-08-02) — `team_power_timeline_scores()` computes
   `wins / games_played` where `games_played = wins + losses + ties`; a
   tie counts toward the denominator but contributes nothing to the
   numerator, so it's scored identically to a loss instead of the
   standard 0.5-win credit. Pre-existing (not introduced by RT-1's
   shrinkage work, which wraps this same formula unchanged), and Sleeper
   ties are rare enough in a points-based scoring format that this hasn't
   mattered in practice — low priority, but a real accuracy gap if it
   ever comes up. Fix: give `wins + 0.5 * ties` credit in the numerator.

## Code quality, tests & UX polish

1. [ ] **CQ-1: Broader test coverage.** `tests/test_dynasty_core.py` and
   `tests/test_player_scoring.py` cover the core ranking/lineup/valuation
   logic, but `sleeper_api.py`/`fantasycalc_api.py` (the retry/session logic
   and cache-TTL behavior itself) and the CLI's error-handling loop still
   have none. Worth building out now that draft-week time pressure is off.
2. [ ] **CQ-2: Better logging solution than `print()`** (user-flagged 2026-07-26) —
   `rookie_draft.py`'s CLI output is all `print()` today; `python_guidelines.md`
   calls for the standard `logging` module instead (levels, no `print()` for
   diagnostics). Worth a dedicated look at how much of the CLI's *report*
   output (as opposed to actual diagnostics/warnings, which already use
   `logger` in `dynasty_core.py`/`player_scoring.py`) should even move to
   `logging` versus staying as direct terminal output, since the report is
   the CLI's actual product, not a diagnostic — evaluate in its own feature
   branch rather than folding into unrelated work.
3. [ ] **CQ-3: Move Docker image tagging to real semantic versioning**
   (user-flagged 2026-08-01) — the image is currently tagged only `:latest`
   and `:<short-sha>` (`.github/workflows/docker-publish.yml`), and the
   Streamlit footer displays that same short SHA (`GIT_SHA` build arg) to
   confirm a NAS deployment picked up a new image — see
   `docs/dynasty-draft-web-app.md`'s "Sidebar league name and version
   footer" and "Docker + CI/CD" sections. A hash is fine for proving the
   deployed image matches a specific commit, but it's not a meaningful
   sequence — there's no way to eyeball "is the NAS running the latest
   real release" or "did this deploy move forward or roll back" the way a
   bumped `v1.3.0` would show at a glance. Would need: a version number
   maintained somewhere (a `VERSION` file, matching the pattern the sibling
   `Finance-Dashboards` project already uses, noted in the Docker section
   above as a deliberate divergence to revisit), a tagging step in
   `docker-publish.yml` alongside (not necessarily instead of) the existing
   `:latest`/`:<short-sha>` tags, and the footer showing the version number
   with the short SHA alongside it for the precise-commit case, not instead
   of it.

## Deferred / low priority

Judged not worth the time right now; revisit only if the underlying
assumption changes.

1. [ ] **DL-1: Handcuff proxy false-positive risk** — depth-chart rank 2 has real
   false-positive risk in modern RB committees. Informational field only,
   not worth revisiting.
2. [ ] **DL-2: Exclude a candidate from its own drop-simulation** in
   `recommend_drop` — theoretically possible, vanishingly unlikely to
   surface as a top pick.
3. [ ] **DL-3: `team_power_timeline_scores`'s all-teams-missing weighted-age
   edge case** (assistant valuation review, 2026-08-01) —
   `weighted_age.fillna(mean)` only recovers if at least one team has a
   valid weighted age; if literally every roster in the league had zero
   players with a positive FantasyCalc value (never observed — same class
   of edge case the code already flags as "never observed, not
   impossible" for the single-team version), the column would stay
   all-`NaN` and silently propagate into every team's `power_score`. Not
   worth guarding given the odds.
4. [ ] **DL-4: Duplicate `positional_strength_summary()` call for the user's own
   roster** (assistant valuation review, 2026-08-01) — now computed once
   via `team_roster_analysis` and again via `team_power_timeline_scores`
   each refresh. Trivial cost at this scale (`gather_state` still
   completes in ~4s); not worth restructuring.
5. [ ] **DL-5: Review "How this works" expanders for content to extract into the
   Glossary** (user-flagged 2026-08-01) — the Glossary dialog
   (`streamlit_app.py`'s `GLOSSARY`) currently only covers VOR, power
   score, and adj. value, added specifically for the power/timeline read.
   Other sections (Roster needs, Draft Plan) still explain their own terms
   inline inside per-section "How this works" expanders (e.g. Roster
   needs' VOR explanation predates the Glossary and was never migrated).
   Worth a pass to find which of those definitions are genuinely
   reusable/cross-cutting (glossary-appropriate) vs. section-specific
   walkthroughs that belong where they are.
