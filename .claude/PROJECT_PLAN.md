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
below): `NB-2`, `RT-24`, `VA-6`, `CQ-7`, `DL-9`.

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
- [ ] `DL-8` — Phase 2 (actual deletion of `.orphaned`-marked snapshot
  files), gated on confirming Phase 1's marking step has run correctly
  against real data at least once.

## Current branch — fix before merge

Findings from reviewing the *active* branch's own not-yet-merged work —
kept separate from the thematic backlog below so "fix this before the PR
merges" is never mixed in with "someday" work. Ephemeral by design: cleared
out when the branch merges, not carried forward as history (the merged PR's
description is the historical record). A finding that gets explicitly
deferred rather than fixed moves down into the appropriate thematic section
below as a normal backlog item, same as any other deferred work.

**Branch:** `feature/rt14-counter-offer-improvement` (PR #41, "RT-14:
evaluate and improve a trade offer someone proposed to us") — reviewed
2026-08-19.

- [ ] **`improve_incoming_offer()`'s partner-tolerance gate uses a stale
  anchor for "theirs"-side variants, letting through some counter-offers
  meaningfully more unfair to the partner than the app's own established
  fairness bar.** `trade.py`'s `tolerance = max(TRADE_OFFER_PARTNER_TOLERANCE_PCT
  * incoming_value, TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE)` is computed once,
  from the *baseline proposal's* `incoming_value` (the value of what the
  partner originally offered), and reused unchanged for every generated
  variant on *both* sides. That's correct for `"yours"` variants (only your
  outgoing package changes; what the partner gives — `incoming_value` — really
  does stay fixed, exactly mirroring `find_trade_offers()`'s own formula,
  where `target_value` is fixed and only your combo varies). It's wrong for
  `"theirs"` variants: there, the swap/add move changes what the partner
  would give you, so `incoming_value` is no longer the deal's fixed
  reference — your own (unchanged) outgoing value is. Concrete failure case:
  partner offers a 500-value target for your fixed 200-value outgoing
  package (baseline `incoming_value = 500`, so `tolerance = max(0.15*500, 25)
  = 75`). A `"theirs, swap"` neighbor replaces that target with a cheaper
  250-value asset from the partner's own sellable pool. The real deal size
  is now ~200–250, so a properly-calibrated tolerance would be ~`max(0.15*250,
  25) = 37.5`, and the swap's real partner-side shortfall (`200 - 250 =
  -50`) should fail that. But the code still uses the stale `75` anchor, so
  `-50 > -75` passes, and the variant gets surfaced as a legitimate
  `"counter"` suggestion — one the app's own convention would reject at a
  smaller deal size. This isn't self-correcting via `_is_good()`: a variant
  that shortchanges the partner is, by construction, a *good* deal for the
  user (that's exactly the case the tolerance gate exists to catch), so
  `_is_good(your_side)` passes easily and the tolerance gate is the only
  thing standing between a fair suggestion and an unrealistic one. None of
  the 7 new tests happen to combine a baseline `incoming_value` large enough
  for the percentage term to dominate (`> ~167`) with a "theirs" swap/add
  that shrinks value — the one test that does exercise `"theirs, add"`
  (`test_counter_ranks_swap_and_add_variants_and_rejects_a_lopsided_drop`)
  uses values low enough that the anchor mismatch doesn't move the outcome.
  **Fix:** anchor tolerance on whichever side of the trade stays fixed for
  the variant being evaluated — `incoming_value` (as today) for `"yours"`
  variants, but the *outgoing* package's value (`your_outgoing_player_ids`/
  `your_outgoing_pick_names`, summed the same way `incoming_value` already
  is) for `"theirs"` variants — rather than one hardcoded anchor used for
  both. Add a test with a baseline `incoming_value` above the ~167
  percentage/floor crossover point and a `"theirs"` swap/add that shrinks
  the incoming side, to lock in the corrected behavior.

  **Fixed 2026-08-19**: `tolerance_by_side` now computes both anchors
  (`incoming_value` for `"yours"`, `outgoing_value` for `"theirs"`) and the
  filtering loop looks up the one matching each variant's `side`, instead
  of one `tolerance` reused for both. Added
  `test_theirs_side_tolerance_is_anchored_on_outgoing_value_not_the_stale_incoming_ask`
  — confirmed it fails against the pre-fix code (`counter` when it should
  be `reject`) and passes against the fix. 214 tests pass.

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

- [ ] **VA-6: Pickup alerts can display "would add +0.0 to your lineup"
  for a marginal value that's real but rounds away** (assistant valuation
  review, 2026-08-19, `feature/pickup-alerts-impact`) —
  `state.py`'s pickup-alert filter (`if value is not None and value > 0`)
  tests `rank_by_marginal_value()`'s raw, unrounded `marginal_value`, then
  passes that same raw value straight through to `summary.py`'s
  `_impact_and_drop_note()`, which formats it to one decimal
  (`f"{marginal_value:+.1f}"`). `free_agent_board()`
  (`dynasty_core/marginal_value.py`) rounds to one decimal *before* an
  identical `> 0` filter runs in `_free_agent_lines()`. A raw marginal
  value in `(0, 0.05)` — real but tiny — passes the pickup-alert filter yet
  renders as `"+0.0"`, so a Pickup alert can literally read "would add +0.0
  to your lineup — would require dropping Starter WR (a starter)": a
  self-contradicting message for the exact same underlying signal that
  `free_agent_board`'s identical filter already exists to keep off the
  board for that player. Bounded in practice (only the `(0, 0.05)` window
  is affected, and the displayed "+0.0" undercuts rather than
  overstates the case for acting on it) — not a wrong recommendation, but
  a confusing one on a feature whose whole point is a trustworthy "what
  this would replace" readout. No existing test exercises this boundary
  (`test_summary.py`'s pickup-alert tests only ever pass whole-number
  `marginal_value`s). Fix: round once in `state.py` (matching
  `free_agent_board`'s convention) and filter/store/sort on that rounded
  value, rather than filtering on the raw float and formatting a different
  precision downstream. See `valuation_principles.md`'s new "a displayed
  number and the filter gating its display must round on the same basis"
  rule.
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
- [ ] **CQ-7: `pick_value_by_name` dict-building + NaN-safe pick-value-sum
  pattern duplicated between `find_trade_offers()` and
  `improve_incoming_offer()`** (assistant valuation review, 2026-08-19) —
  both build `dict(zip(pick_value_table["pick"], pick_value_table["value"]))`
  and both sum a list of pick names against it with the same
  `pd.notna()`-filtered pattern (`improve_incoming_offer()`'s `_pick_value_sum`
  vs. `find_trade_offers()`'s inline `pick_value_by_name.get(...)` reads).
  Minor — no behavioral risk, both copies are already NaN-safe per
  `valuation_principles.md`'s NaN rule — but worth extracting a small shared
  helper (e.g. `_pick_value_lookup(pick_value_table)` returning both the
  dict and a `sum(names)` closure) next time either function is touched,
  rather than a third copy appearing.

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
- [ ] **DL-8: Actually delete orphaned, `.orphaned`-marked
  `draft_snapshots_{draft_id}.json` files** (deferred from `RT-20`,
  2026-08-06; Phase 1 shipped 2026-08-17) — two-phase by deliberate
  choice, not deletion logic that just happened to land half-built.
  **Phase 1 (done):** `draft_snapshots.py`'s `_mark_orphaned_snapshots`,
  called as a side effect of every `reconcile_snapshot()` call, renames
  (never deletes) any `draft_snapshots_*.json` file older than
  `ORPHAN_AGE_DAYS` (90) that isn't the draft currently being reconciled,
  appending `.orphaned` — a soft, reversible, visibly-inspectable marker
  instead of automated deletion on a hot path an active draft depends on.
  Verified against a copy of this repo's own real `.cache/` file: the
  current draft's file is left untouched, an aged copy gets marked
  correctly, content otherwise fully preserved either way.
  **Phase 2 (this item, still open):** actually delete `.orphaned` files
  — user-requested as an explicit second step, gated on confirming Phase 1
  has run correctly against real data in practice (the NAS deployment, a
  real refresh cycle) at least once, not assumed correct from launch.
  Revisit once that confirmation has happened.
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
