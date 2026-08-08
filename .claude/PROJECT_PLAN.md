# Project Plan

Grouped by theme; within each group, items are ordered by priority (most
important first). When a task is completed, remove its entry from this list
immediately — the commit/PR that closed it is the historical record (the
same principle the "Current branch — fix before merge" section already
applies, generalized to every item here). A durable design decision or
methodology worth keeping belongs in `CLAUDE.md`, `docs/`, or
`.claude/conventions/valuation_principles.md`, not in a completed item's
write-up here — this file is only what's left to do.

**Item IDs**: every open item carries a permanent `<SECTION>-<n>` tag in its
own heading (`NB` = Now — blocking, `RT` = Roster & trade tooling, `VA` =
Valuation & data accuracy, `CQ` = Code quality/tests/UX, `DL` = Deferred/low
priority) — e.g. `RT-3`. Assigned once, in document order, and never reused
or renumbered, even after the item it names is completed and its entry
deleted — matching how `VA`'s items were already informally lettered A-E
before this convention was written down (`A`/`B`/`E` are done and gone; `D`
survives as `VA-1`). Cross-reference other items by this tag (`see RT-3`),
never by list position (`item 2`) — a positional reference silently points
at the wrong item the moment anything above it is inserted, reordered, or
removed. A new item gets the next unused number for its section's prefix,
appended wherever priority order actually puts it in the list — position and
ID are independent. Since a completed item's entry is deleted rather than
archived, the next-unused number per prefix can't be found by scanning the
file once nothing with that prefix remains — it's tracked explicitly in the
**ID tracker** below instead; bump the matching entry there the moment a new
item is filed, regardless of whether the file currently shows any item with
that prefix. Each item is a plain bullet (`- [ ]`), never a numbered list
entry — a numeric list marker is exactly the kind of position-dependent
detail this convention exists to avoid; the bold `<SECTION>-<n>:` lead-in is
the only identifier that matters, and it never needs renumbering when an
item above it is added or removed. The ephemeral "Current branch — fix
before merge" section is exempt from ID tagging (cleared on every merge, so
nothing outlives it to cross-reference) but still uses plain bullets.

**ID tracker** (last number assigned per prefix — bump this the moment a new
item is filed, whether or not any item with that prefix still appears
below): `NB-2`, `RT-24`, `VA-5`, `CQ-5`, `DL-9`.

## Short list — actively prioritized right now

A small, hand-curated pointer into the backlog below — not a duplicate of
any item's content, just which `<SECTION>-<n>` tags are getting real
attention right now and why, so that's visible without reading the whole
file. Keep each tier to a handful of items; if either grows past ~5-6,
it's stopped being a "short" list — thin it back out to what's actually
active. Remove an item once it's done (its own full entry gets removed
too, per the convention above), don't let this become a history log.

**Nice to have (no deadline, worth doing when there's room):**
- [ ] `RT-4` — infer the rebuild-vs-contend phase shift from the existing
  power/timeline read instead of a manually-set phase.
- [ ] `DL-7` — table column overflow on the rookie big board (downgraded
  after live phone testing showed it's manageable today).

## Current branch — fix before merge

Findings from reviewing the *active* branch's own not-yet-merged work —
kept separate from the thematic backlog below so "fix this before the PR
merges" is never mixed in with "someday" work. Ephemeral by design: cleared
out when the branch merges, not carried forward as history (the merged PR's
description is the historical record). A finding that gets explicitly
deferred rather than fixed moves down into the appropriate thematic section
below as a normal backlog item, same as any other deferred work.

**`feature/rt-15-suggested-trades` (PR #34), reviewed 2026-08-08:**

- [ ] `suggested_trades()` (`dynasty_core/trade.py`) never checks whether
  the trade it's about to recommend is actually good for the user before
  showing it. Stage 1 (`leaguewide_trade_candidates()`) correctly filters
  to `marginal_value > 0` before a candidate is even considered — matching
  `free_agent_board`/`pickup_alerts`' "worth surfacing at all" convention
  — but Stage 2 doesn't carry that standard forward: it only requires
  `find_trade_offers()`'s `offers` list to be non-empty (some combo
  cleared the *partner's* plausibility bar), then sorts survivors by
  `your_side["lineup_delta_after_drops"]` and shows the top 3 with no
  floor at zero. A candidate whose only viable offer is net-neutral, or
  actually negative, for the user's own lineup can still be ranked and
  shown as a "Suggested Trade" — the branch's own new test proves this
  directly (`TestSuggestedTrades::test_drops_candidates_with_no_viable_offer_and_ranks_survivors_by_lineup_gain`
  constructs `target_a` with `lineup_delta_after_drops == 0.0` and asserts
  it survives into the result list, ranked #2, rather than being dropped).
  This is a new risk specific to this feature's automation: the manual
  trade-target optimizer it replaces always showed a human the target's
  own `target_read` ("worth pursuing," computed for free) before the
  human decided to run a search at all; Suggested Trades removes that
  checkpoint by auto-selecting candidates and auto-presenting the ranked
  results as the feature's whole value proposition. Fix: filter `results`
  in `suggested_trades()` to `your_side["lineup_delta_after_drops"] > 0`
  before sorting/capping to `top_n`, mirroring Stage 1's own filter — and
  update the test above, since a `0.0`-delta candidate should now be
  dropped rather than ranked. Captured as a durable rule in
  `valuation_principles.md`'s new "worth surfacing" filter section.

## Now — blocking

Empty right now — nothing blocking.

## Roster & trade tooling

Originally scoped as explicitly post-draft (user-flagged 2026-07-26), then
briefly reordered 2026-07-30 to put trade targets & sells first given real
trade talk already happening pre-draft, then reordered again same day: the
user judged that shipping trade targets & sells before the positional-value
and team-power foundations it needs would produce a weak tool that has to
be redone once those land, so the foundations come first. Still bumped
ahead of Valuation & data accuracy below, which remains explicitly not
deadline-driven.

Deliberately out of v1, not forgotten:
- **Selling starters, not just depth** — the "sellable vs. just
  droppable" line for a position's own top-value players (not bench
  surplus) is a much bigger strategic call (trade away a good win-now
  asset for future value, core to a rebuild) than "there's unused depth
  here." Left for a human to judge directly against a specific offer,
  not modeled.
- **Draft-pick ownership beyond next season** — Sleeper's `traded_picks`
  has no fixed "how many years out" window, only entries for picks
  actually traded (`FUTURE_PICK_YEARS_AHEAD = 1` in `dynasty_core/picks.py`).
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

- [ ] **RT-14: Evaluate and improve an offer someone else has already made
  *to* us** (user-flagged 2026-08-02, filed while scoping `RT-12`) — a
  third, distinct question alongside the trade evaluator (`RT-2`: score a
  fully-specified trade) and the trade-target optimizer (`RT-12`: given a
  target, decide whether to pursue it and what to offer for it). Here the
  *partner* has proposed a specific trade to us; this would (1) evaluate it
  exactly like the manual trade evaluator already does — no new logic
  needed for that half — and then (2) suggest how to *improve* it: a
  counter-offer search, structurally close to `find_trade_offers()`'s
  combinatorial search but starting from the partner's actual proposed
  assets as a baseline to adjust (add/swap/drop an asset on either side)
  rather than searching from scratch against a single target. Likely
  reuses the bulk of `find_trade_offers()`'s search/scoring machinery
  rather than inventing a second one — worth checking during scoping
  whether the two can share a common search helper instead of duplicating
  the combo-generation/plausibility-gate logic twice.
- [ ] **RT-16: Need-match tiebreaker in `find_trade_offers()` reuses
  `roster_needs_summary`'s rebuild-timeline "need" flag on the *partner's*
  roster, which may not mean what it implies for a partner not running the
  same rebuild strategy** (assistant valuation review, 2026-08-02) —
  `need` is specifically "fewer than `YOUNG_CORE_NEED_THRESHOLD` young
  players at this position" (`docs/rookie-draft-big-board.md`'s "two
  different signals" section), a rebuild-*timeline* question, not a
  general "does this team want more here" signal. Every other place this
  project uses `need_positions()` applies it to the *caller's own* roster
  to bias the caller's own draft/trade choices toward their own rebuild
  plan (`RT-4` is the open item tracking that this flag should evolve with
  rebuild phase at all). `find_trade_offers()` is the first place it's
  applied to someone *else's* roster to guess what they'd want — a
  win-now partner might not care about "young core" at this position at
  all, or might specifically want to trade youth away for a proven
  veteran, the opposite of what the flag implies. Low severity since it's
  explicitly a ranking tiebreaker only (already noted in the function's
  own docstring, never the accept/reject gate), but worth either a doc
  caveat that this tiebreaker assumes every partner is need-reading the
  same way a rebuilding team would, or reconsidering what "need" should
  mean when read on someone else's roster.
- [ ] **RT-23: Suggested Trades - optional position-scope filter** (user-flagged
  2026-08-08, noted future option, not v1 scope, while building `RT-15`) —
  besides the single-target filter, also let the user scope leaguewide
  suggestions by position (e.g. "show me RB opportunities only") - a
  second, independent optional filter within the same section, not a
  replacement for the target filter. Not needed for the first cut; revisit
  now that leaguewide scanning itself is built and the section's filter UI
  exists to extend (see `docs/rookie-draft-big-board.md`'s "Suggested
  Trades" section).
- [ ] **RT-24: Suggested Trades' cached scan results go stale across a
  refresh, with no invalidation** (assistant valuation review, 2026-08-08)
  — `trade_tab.py`'s "Scan the league for offers" button stores its result
  in `st.session_state["suggested_trades_results"]` specifically so it
  survives an unrelated rerun without re-scanning (per its own docstring:
  "rather than needing a re-click on every unrelated page interaction").
  But nothing clears or recomputes it when the user clicks the page's own
  "Refresh" and pulls a fresh `gather_state()` snapshot — every other
  field in `state` is rebuilt from scratch on refresh, but this one result
  silently keeps showing whichever combo/target a *previous* refresh
  computed, even after a real roster change elsewhere (another manager's
  trade, a waiver claim) could have made it stale or outright impossible.
  Low severity for a single-user personal tool — a stale suggestion just
  fails obviously the moment it's acted on for real in Sleeper — but worth
  clearing `suggested_trades_results` from session state whenever a fresh
  refresh runs, so a scan can never outlive the snapshot it was computed
  against.
- [ ] **RT-4: Make "need"/strategy phase-aware — a static rule today, should
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
  sudden uptick in opportunity/fortune (this is exactly what the in-season
  pickup monitor now surfaces via the Summary tab's "Pickup alerts") — and
  dropping deadweight with limited
  future payoff (already partly modeled by `roster_value_analysis`'s
  `LOW_VALUE_AGING_AGE` cutoff, but not tied to a rebuild-year concept
  either). Would need an explicit "what phase of the rebuild are we in"
  input (probably just a manually-set year/phase, not inferred) that
  shifts behavior across `need`, drop-candidate, and free-agent-flagging
  logic, rather than one flat rule doing double duty for every year.
  Related to but distinct from the positional-value work above — that's
  about *which position* is weak; this is about *what kind of move* the
  team should even be looking for at this point in the rebuild.
  **Refined 2026-08-06** (user-flagged, future consideration, not an
  immediate concern): the trigger for a phase change is probably
  performance-tier, not just elapsed time — `need`'s young-core framing
  is well-suited to a bottom-of-standings rebuild, but if the team moves
  into mid/upper-table performance, "need" should mean something
  different (roster-hole-driven, not youth-accumulation-driven), and nothing
  today would notice that shift happened. Worth checking before assuming
  this needs a manually-set phase input at all: `team_power_timeline_scores()`
  already computes a continuous rebuild-vs-contend read (`power_score`,
  split into `quality_score`/`timeline_score`) for every team, every
  refresh — a real candidate for *inferring* the phase transition directly
  rather than asking the user to track and set it by hand. Doesn't change
  the scope of the work itself, just a candidate input worth evaluating
  when this is actually picked up.
- [ ] **RT-5: League tab — all-teams summary view** (user-flagged 2026-07-29,
  longer term). A compact row per team (total roster value, biggest need,
  capacity) to scan the whole league at a glance before drilling into one
  team, complementing the Roster tab's team selector (added
  2026-07-29), which only ever shows one team at a time. Cheaper than it
  would have been before that selector shipped —
  `dynasty_core.team_roster_analysis()` already runs this exact per-team
  analysis for any roster on demand; this is "call it for all ~12 teams
  and lay out a summary row," not new analysis logic. A natural
  lighter-weight complement to the power/timeline read
  (`team_power_timeline_scores()`) — this surfaces raw stats per team, not a
  rebuild-vs-contend classification, but both answer "what does this team
  look like" at a glance.
- [ ] **RT-6: Contextual research check for news/hype beyond Sleeper's data**
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
- [ ] **RT-7: Use `points_for`/point differential as a steadier alternative
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
- [ ] **RT-8: Model real taxi-squad eligibility for free-agent adds**
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
  rearchitecture.
- [ ] **RT-21: Sleeper's transaction log as a secondary data source —
  revisit before next year's draft** (assistant-flagged 2026-08-07, filed
  while scoping `RT-20`, user-flagged as worth keeping for later rather
  than acting on now) — `RT-20` was built as a roster-snapshot-and-diff
  design, but a live check against this league's real API during scoping
  found Sleeper's `/league/{id}/transactions/{leg}` endpoint already
  records every real roster move with a timestamp, including plain
  "drop to make room" cuts (`type: "free_agent"`, `adds: null`, a real
  `drops: {player_id: roster_id}`). Two distinct reasons this could be
  worth building out, not investigated further this pass given draft-day
  time pressure:
  - **Closing `RT-20`'s own gap.** Its `"ambiguous"` state exists because
    a roster-diff snapshot can't isolate which drop paired with which pick
    when two or more of the user's own picks complete in the same refresh
    gap. Sleeper's transaction log doesn't have this problem — it's
    timestamped and complete regardless of when this app happens to
    refresh — though it introduces a different gap instead: Sleeper
    doesn't timestamp individual draft picks, so pairing a transaction to
    a specific pick would still need a positional/count-based heuristic,
    not a hard fact. Unverified going into this: whether draft-day cuts
    always land as `type: "free_agent"` (vs. some other transaction type),
    and `league["settings"]["leg"]`'s bucketing behavior beyond the
    single `leg=1` value checked live (this league was still in
    `"pre_draft"` status with zero picks made at check time, so no
    real "cut immediately following a draft pick" example existed yet to
    validate against).
  - **Leaguewide visibility, not just the user's own roster** — the same
    endpoint returns every team's transactions, not just the user's,
    which `RT-20`'s snapshot design has no equivalent for (it only ever
    diffs the user's own roster). Could show what other teams are doing
    during the draft (real drops/adds leaguewide) as a genuinely new
    signal, not just a more-reliable version of `RT-20`'s existing one —
    worth scoping as its own feature rather than folding entirely into
    `RT-20`'s drop-attribution problem.
  Revisit ahead of next year's rookie draft, with time to verify the
  unconfirmed assumptions above against a real draft in progress before
  committing to a design — not urgent mid-draft the way `RT-20` was.
- [ ] **RT-10: FAAB bid-threshold modeling** (deferred from the free-agent
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

## Valuation & data accuracy

Not deadline-driven the way the group above now is (see 2026-07-30 note) —
this is about improving accuracy for ongoing dynasty decisions, not a hard
cutoff.

- [ ] **VA-1 (formerly "D"): blend in KeepTradeCut as a second market source**, time
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
- [ ] **VA-2: Derive `BASELINE_SCORING`'s `rec` value from the real `ppr` param
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
- [ ] **VA-3: Automate `scripts/derive_position_multipliers.py` re-derivation.**
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
- [ ] **VA-4: Post-draft valuation retrospective** (assistant valuation review,
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

- [ ] **VA-5: `win_pct` doesn't credit a tie as half a win** (assistant
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

- [ ] **CQ-1: Broader test coverage.** `tests/dynasty_core/` and
  `tests/test_player_scoring.py` cover the core ranking/lineup/valuation
  logic, but `sleeper_api.py`/`fantasycalc_api.py` (the retry/session logic
  and cache-TTL behavior itself) and the CLI's error-handling loop still
  have none. Worth building out now that draft-week time pressure is off.
- [ ] **CQ-2: Better logging solution than `print()`** (user-flagged 2026-07-26) —
  `rookie_draft.py`'s CLI output is all `print()` today; `python_guidelines.md`
  calls for the standard `logging` module instead (levels, no `print()` for
  diagnostics). Worth a dedicated look at how much of the CLI's *report*
  output (as opposed to actual diagnostics/warnings, which already use
  `logger` in `dynasty_core.py`/`player_scoring.py`) should even move to
  `logging` versus staying as direct terminal output, since the report is
  the CLI's actual product, not a diagnostic — evaluate in its own feature
  branch rather than folding into unrelated work.
- [ ] **CQ-3: Move Docker image tagging to real semantic versioning**
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
- [ ] **CQ-5: Represent draft-pick identity as structured fields at ingestion, not a
  display string re-parsed downstream** (user-suggested, 2026-08-07, filed while
  reviewing the RT-18 pick-callout season bug above) — `pick_trade_values()` already
  builds a formatted `"pick"` label per row (`"2026 Pick 1.01"` this season, `"2027
  1st"` next season) as effectively the only column that encodes season/round, so
  every downstream consumer that needs the season or round has to re-parse that label
  — `_pick_context_callouts()`'s now-fixed `" Pick "` split was one instance;
  `trade_tab.py`'s pick-selection/labeling helpers likely re-derive similarly. The
  general principle: parse an externally- or internally-generated composite string
  once, at the point it's produced, into real fields with a well-defined "unknown"
  case — not repeatedly downstream, where each call site can (and, once already did)
  parse it differently or incompletely. Concretely: give `pick_trade_values()`'s output
  real `season`/`round` (and `slot` where it exists) columns alongside the display
  `"pick"` label, and move every downstream consumer that currently
  slices/splits/matches the label for meaning (grouping by class, sorting by round)
  over to those columns instead — the label stays purely a rendering concern. Distinct
  from `pick_trade_values()`'s own name-string matching against FantasyCalc's data
  (`valuation_principles.md`'s "opaque keys" rule) — that's an external join key and
  has to stay a string match; this is about not re-deriving *this codebase's own*
  already-known structure from a string it built. Cleanup scope, not urgent — no
  known live bug beyond the one already fixed above.

## Deferred / low priority

Judged not worth the time right now; revisit only if the underlying
assumption changes.

- [ ] **DL-1: Handcuff proxy false-positive risk** — depth-chart rank 2 has real
  false-positive risk in modern RB committees. Informational field only,
  not worth revisiting.
- [ ] **DL-2: Exclude a candidate from its own drop-simulation** in
  `recommend_drop` — theoretically possible, vanishingly unlikely to
  surface as a top pick.
- [ ] **DL-3: `team_power_timeline_scores`'s all-teams-missing weighted-age
  edge case** (assistant valuation review, 2026-08-01) —
  `weighted_age.fillna(mean)` only recovers if at least one team has a
  valid weighted age; if literally every roster in the league had zero
  players with a positive FantasyCalc value (never observed — same class
  of edge case the code already flags as "never observed, not
  impossible" for the single-team version), the column would stay
  all-`NaN` and silently propagate into every team's `power_score`. Not
  worth guarding given the odds.
- [ ] **DL-4: Duplicate `positional_strength_summary()` call for the user's own
  roster** (assistant valuation review, 2026-08-01) — now computed once
  via `team_roster_analysis` and again via `team_power_timeline_scores`
  each refresh. Trivial cost at this scale (`gather_state` still
  completes in ~4s); not worth restructuring.
- [ ] **DL-6: `team_name_by_roster_id` can show a duplicated name**
  (assistant valuation review, 2026-08-02) — if an owner's custom Sleeper
  `team_name` happens to equal their `display_name` (username), the
  combined label reads "Bob (Bob)" instead of collapsing to just "Bob".
  Cosmetic edge case, not worth guarding.
- [ ] **DL-5: Review "How this works" expanders for content to extract into the
  Glossary** (user-flagged 2026-08-01) — the Glossary dialog
  (`streamlit_app.py`'s `GLOSSARY`) currently only covers VOR, power
  score, and adj. value, added specifically for the power/timeline read.
  Other sections (Roster needs, Draft Plan) still explain their own terms
  inline inside per-section "How this works" expanders (e.g. Roster
  needs' VOR explanation predates the Glossary and was never migrated).
  Worth a pass to find which of those definitions are genuinely
  reusable/cross-cutting (glossary-appropriate) vs. section-specific
  walkthroughs that belong where they are.
- [ ] **DL-7: Table columns overflow the viewport, forcing horizontal
  scroll** (user-flagged 2026-08-06, then downgraded same day after
  testing live on a phone: "wasn't too bad even there — easy to pull to
  the side and see what's hidden") — every table renders through one
  shared `show_df()`/`cols()` path (`tabs/components.py`), so a fix
  applies everywhere at once if it's ever worth doing. Currently a Draft
  Board-only concern in practice — the rookie big board is the one table
  wide enough to matter (11 columns: Rank, Player, Position, Fits Need,
  Handcuff To, Drafted Round, Drafted By, Team, College, Age, Value, Adj.
  Value), and `st.dataframe(..., width="stretch")` doesn't prevent that
  from needing its own internal horizontal scroll. If it's ever worth
  revisiting: a smaller default column set with the rest on demand (a
  details expander/modal, a column-visibility toggle), or collapsing
  related columns (Value + Adj. Value into one, raw number as a hover
  detail — the pattern the Trade Evaluator's `lineup_delta`/
  `lineup_delta_after_drops` already uses).
- [ ] **DL-8: Orphaned `draft_snapshots_{draft_id}.json` files are never
  cleaned up** (deferred from `RT-20`, user-flagged as fine to defer,
  2026-08-06) — once a season's rookie draft is fully over, its snapshot
  file is simply never read again (next season gets a new `draft_id` from
  Sleeper), so it's harmless to leave behind, just permanent clutter in
  `.cache/`. No retention/cleanup logic was built in `RT-20`'s first pass.
  Revisit only if `.cache/` growth ever actually matters.
- [ ] **DL-9: Non-fantasy-position filtering happens per-consumer, not once
  at ingest** (user-flagged 2026-08-08, verified during the RT-15 planning
  pass) — `sleeper_api.get_players()` caches Sleeper's full ~14MB/~10k-player
  dataset as-is (every NFL position, including defense/kicker/etc., which
  this league's `roster_positions` has no slot for at all). Audited every
  direct consumer of the raw `players` dict for a leak (`player_pools.py`'s
  `rookie_pool`/`free_agent_pool`/`roster_fantasy_players`/
  `fantasy_relevant_teamed_players`, `lineup.py`'s `player_value_rows`,
  `roster_needs.py`'s `position_replacement_levels`, `trade.py`'s
  candidate-building) — every one of them already checks
  `position in FANTASY_POSITIONS` before a player reaches any real
  computation, so no live bug was found. But the guarantee is enforced by
  convention at each call site, not structurally at the source — a new
  consumer that iterates the raw `players` dict and forgets the check
  would silently let an irrelevant position through. Worth consolidating
  to a single ingest-time (or single shared-helper) filter if a new
  consumer of raw `players` is ever added; not urgent since nothing is
  broken today.
