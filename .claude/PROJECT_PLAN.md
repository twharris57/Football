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

## Roster & trade tooling

Originally scoped as explicitly post-draft (user-flagged 2026-07-26), then
briefly reordered 2026-07-30 to put trade targets & sells first given real
trade talk already happening pre-draft, then reordered again same day: the
user judged that shipping trade targets & sells before the positional-value
and team-power foundations it needs would produce a weak tool that has to
be redone once those land, so the foundations come first. Still bumped
ahead of Valuation & data accuracy below, which remains explicitly not
deadline-driven.

**Positional-value foundation done (2026-07-31, SUPER_FLEX/QB fix
2026-08-01)** — see `docs/rookie-draft-big-board.md`'s "Roster needs: two
different signals, not one" for the full methodology.
`positional_strength_summary()` + `position_replacement_levels()` add a
`vor`/`weak` value-over-replacement signal, joined onto the existing
young-core `need` flag, using a league-wide replacement-level baseline
(deliberately not a same-roster share-of-value metric — see the doc for
why that has a real flaw). `_position_starter_demand()` counts SUPER_FLEX
as extra QB demand specifically (matching the `num_qbs` pattern already
used for the FantasyCalc market-value call) — a same-day valuation review
caught that the first version silently reverted QB to single-QB-league
demand, which would have systematically understated QB's VOR for
everything built on top of it. Verified directly against live data (the
league-wide rank-24 replacement QB is a real, independently-confirmed
player, not a self-referential artifact). Works through the Your Roster
tab's team selector for any team, not just the user's own.

1. [ ] **League-wide power/timeline read** — place every team in the league
   on a rebuild-vs-contend spectrum, to identify good trade partners
   (contenders who overpay for immediate help, rebuilders who overpay for
   future assets). Build on the positional-value work above applied
   per-team, not a separate model — a team's overall power/timeline is
   naturally a roll-up of how strong/weak/young/old each of its positions
   is. Feeds item 2.

   **Follow up on this line of thinking when actually building it**
   (user-flagged 2026-08-01): a two-point rebuild-vs-contend spectrum is
   probably too coarse. The user's framing has at least three phases -
   rebuilding, running for a title, and just finishing the season out at a
   decent level (a real, distinct state - not full rebuild mode, but not
   actively pushing for a title either) - and phase isn't fixed for a
   season: it can shift mid-season on a real event (a team realizing
   they're one piece away from a title run, or a season/career-ending
   injury ending a contender's hopes). A single label computed once per
   refresh and left alone would go stale exactly when it matters most
   (right after the event that should have changed it). Whatever this
   read feeds into (trade targets, in-season monitoring) should account
   for a team's phase actually moving, not just where it started the
   season - worth deciding at build time whether that means recomputing
   fresh every refresh (cheap if it's just derived from current roster
   state, which reacts to injuries/moves already) versus something more
   deliberate. Same lifecycle-phase concept applies to item 4's "make
   need/strategy phase-aware" for the user's *own* team, not just other
   teams here - worth keeping the two consistent rather than solving the
   same problem two different ways.

   **Consider a continuous score, not just discrete phase labels**
   (assistant valuation review, 2026-07-31): the three-phase framing above
   is a good user-facing description, but implementing the underlying
   computation as a continuous index (e.g. derived from the roster's
   aggregate VOR and age profile, now that the SUPER_FLEX/QB fix above has
   landed) rather than jumping straight to a fixed small set of discrete
   buckets would avoid re-litigating "how many phases" a third time later
   — display labels can still be thresholds on that continuous score.
2. [ ] **Trade targets & sells** — given the rebuild strategy, flag which
   of the user's veterans are sellable for picks, and which other teams'
   picks/young players might be realistically available. Deliberately
   sequenced after item 1, not before: "sellable" can already lean on the
   positional-value work above (a valuable player at a *deep* position is
   a better sell than an equally valuable one at a *thin* one), but "what's
   realistically available" from another team still needs a real
   rebuild-vs-contend read on them, not just their lowest-value players —
   building this before item 1 would produce a weak v1 that has to be
   redone once it exists. Should extend to **trade-block monitoring**
   (user-flagged 2026-08-01): watch for players another team is actively
   shopping and score them against the current roster the same way the
   free-agent evaluator's in-season pickup monitoring does (item 3) —
   season-average marginal starting-lineup value, not raw trade value —
   flagging only when a specific player would be a genuine value-add, not
   every trade rumor. Needs a real signal for "this player is on the
   block" first (Sleeper doesn't expose trade discussions directly, so
   this likely means the user manually flagging a name to check rather
   than a real feed, at least for v1). A manually-flagged name here is
   also a natural fit for item 6's contextual research check, once that
   exists — pulling real context (usage change, injury detail, actual
   trade buzz) beyond what Sleeper/FantasyCalc carry, for that one
   specific player.

   **Sellable vs. just droppable** (user-flagged 2026-08-01): the "sellable
   veterans" side of this needs a real line between "worth trying to
   trade" and "worth just cutting" - not the same question as the
   existing low-value/aging drop-candidate flag in `roster_value_analysis`
   (and `recommend_drop`/`best_position_relevant_drop`, which already
   answer "who to drop" once a roster spot is genuinely needed). A player
   can be too marginal to keep but still have enough real market value
   (FantasyCalc `value`, or scarcity at a thin position elsewhere in the
   league per `positional_strength_summary`'s `vor` signal, done above)
   that shopping them first beats just cutting them for nothing. Where
   exactly that line sits is worth deciding when this is actually built,
   not guessed at now.

   **Reuse existing signals for that line, don't invent a new one**
   (assistant valuation review, 2026-07-31): a player is a better
   sell-first candidate the more `positional_strength_summary`'s `vor` at
   their position clears zero (real surplus, not just headcount) and the
   less dropping them would open a `roster_weekly_gaps`/`gap_delta` hole —
   both already computed elsewhere in the pipeline. Composing existing
   signals here, rather than a new bespoke threshold, matches the
   project's own lesson from merging the old Strategy tab into Draft Plan
   (`docs/dynasty-draft-web-app.md`) after two separate ranking methods
   turned out to disagree — see
   `.claude/conventions/valuation_principles.md`.

   **Valuing draft picks in trades** (user-flagged 2026-08-01) — confirmed
   directly: `fantasycalc_api.get_dynasty_values()` already returns draft
   picks (`position: "PICK"`) on the same value scale as players, in every
   pull this project already makes — currently silently discarded
   everywhere by the `FANTASY_POSITIONS` (QB/RB/WR/TE-only) filter, not
   something needing a new API integration. This year's remaining picks
   (`2026 Pick 1.01`, etc.) could get an exact value once matched to real
   ownership via the existing `compute_pick_ownership`/`traded_picks`
   machinery (round + owner already tracked there). Future years are only
   ever generic buckets - `2027 1st (Early/Mid/Late)`, flattening to a
   single `2028 1st`/`2029 1st` etc. with no tier the further out it gets -
   since exact future draft slot isn't knowable in advance; that's a real
   approximation to be explicit about, not a gap to try to solve exactly.
   Needed for this item to evaluate anything beyond pure player-for-player
   trades, which is most real dynasty trade offers.

   **Picks don't need the real-scoring correction** (assistant valuation
   review, 2026-07-31): unlike players, a pick isn't tied to any real or
   projectable statistical production, so it should use FantasyCalc's raw
   `value` directly — not routed through `fc_value_by_sleeper_id`'s
   per-player `adj_value` multiplier (`player_scoring.py`), which only
   makes sense for an entity with real or combine-projected stats. Worth a
   comment at the call site when this is built so a future edit doesn't
   try to force picks through that pipeline by habit.
3. [ ] **Free agent / roster-moves evaluator** — a tool for right-now
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

   **FAAB budget awareness** (user-flagged 2026-08-01): this league does
   use FAAB, not priority-only waivers (confirmed directly - league
   `settings.waiver_budget: 100`, `waiver_type: 2`). Any real add
   recommendation needs the bidding-budget picture, not just "is this
   player worth adding": the user's own remaining budget
   (`roster["settings"]["waiver_budget_used"]`, confirmed available per
   team directly from `get_rosters()` - no separate endpoint needed),
   ideally every other team's remaining budget too (a league where
   everyone else is broke changes what a given player is actually worth
   bidding), and the opportunity cost of spending it now vs. saving it for
   a bigger add later in the season. This is a real gap in "worth an add"
   as currently scoped - a player can be a genuine value-add and still be
   a bad bid if it's most of the budget for a marginal upgrade with a
   bigger name likely to hit waivers in a few weeks.

   **Scope v1 to a threshold flag, not full opportunity-cost modeling**
   (assistant valuation review, 2026-07-31): "spend now vs. save for
   later" is genuinely an optimal-stopping problem with no clean
   closed-form answer here. A reasonable v1 is flagging when a
   recommended bid would consume more than some threshold share of
   remaining budget for a pickup that wouldn't crack the starting lineup,
   rather than modeling the full tradeoff up front — matches the
   project's existing pattern of shipping a deliberately lightweight v1
   (e.g. `POSITION_VALUE_MULTIPLIER` before the full per-player recompute)
   over a fully general model nobody's asked for yet.
4. [ ] **Make "need"/strategy phase-aware — a static rule today, should
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
   sudden uptick in opportunity/fortune (this is exactly item 3's
   in-season pickup monitoring) — and dropping deadweight with limited
   future payoff (already partly modeled by `roster_value_analysis`'s
   `LOW_VALUE_AGING_AGE` cutoff, but not tied to a rebuild-year concept
   either). Would need an explicit "what phase of the rebuild are we in"
   input (probably just a manually-set year/phase, not inferred) that
   shifts behavior across `need`, drop-candidate, and free-agent-flagging
   logic, rather than one flat rule doing double duty for every year.
   Related to but distinct from the positional-value work above — that's
   about *which position* is weak; this is about *what kind of move* the
   team should even be looking for at this point in the rebuild.
5. [ ] **League tab — all-teams summary view** (user-flagged 2026-07-29,
   longer term). A compact row per team (total roster value, biggest need,
   capacity) to scan the whole league at a glance before drilling into one
   team, complementing the Your Roster tab's team selector (added
   2026-07-29), which only ever shows one team at a time. Cheaper than it
   would have been before that selector shipped —
   `dynasty_core.team_roster_analysis()` already runs this exact per-team
   analysis for any roster on demand; this is "call it for all ~12 teams
   and lay out a summary row," not new analysis logic. A natural
   lighter-weight precursor to item 1's power/timeline read, not a
   replacement for it — this surfaces raw stats per team, not a
   rebuild-vs-contend classification.
6. [ ] **Contextual research check for news/hype beyond Sleeper's data**
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
   user's working label for the idea. Natural entry points: item 2's
   trade-block monitoring (checking one flagged name) and item 3's
   free-agent evaluator (checking one waiver target) — not a general
   always-on feed, and not a replacement for the stats-based ranking
   anywhere in the pipeline.

## Valuation & data accuracy

Not deadline-driven the way the group above now is (see 2026-07-30 note) —
this is about improving accuracy for ongoing dynasty decisions, not a hard
cutoff. E (multiplier data pooled across 3 seasons), B (full per-player
scoring recompute), and A (finer position/play-style multiplier buckets,
rescoped to rookies only) are done — see `docs/rookie-draft-big-board.md` for
methodology.

1. [ ] **D — blend in KeepTradeCut as a second market source**, time
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
2. [ ] **Derive `BASELINE_SCORING`'s `rec` value from the real `ppr` param
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
3. [ ] **Automate `scripts/derive_position_multipliers.py` re-derivation.**
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
4. [ ] **Post-draft valuation retrospective** (assistant valuation review,
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

## Code quality, tests & UX polish

1. [ ] **Broader test coverage.** `tests/test_dynasty_core.py` and
   `tests/test_player_scoring.py` cover the core ranking/lineup/valuation
   logic, but `sleeper_api.py`/`fantasycalc_api.py` (the retry/session logic
   and cache-TTL behavior itself) and the CLI's error-handling loop still
   have none. Worth building out now that draft-week time pressure is off.
2. [ ] **Better logging solution than `print()`** (user-flagged 2026-07-26) —
   `rookie_draft.py`'s CLI output is all `print()` today; `python_guidelines.md`
   calls for the standard `logging` module instead (levels, no `print()` for
   diagnostics). Worth a dedicated look at how much of the CLI's *report*
   output (as opposed to actual diagnostics/warnings, which already use
   `logger` in `dynasty_core.py`/`player_scoring.py`) should even move to
   `logging` versus staying as direct terminal output, since the report is
   the CLI's actual product, not a diagnostic — evaluate in its own feature
   branch rather than folding into unrelated work.

## Deferred / low priority

Judged not worth the time right now; revisit only if the underlying
assumption changes.

1. [ ] **Handcuff proxy false-positive risk** — depth-chart rank 2 has real
   false-positive risk in modern RB committees. Informational field only,
   not worth revisiting.
2. [ ] **Exclude a candidate from its own drop-simulation** in
   `recommend_drop` — theoretically possible, vanishingly unlikely to
   surface as a top pick.
