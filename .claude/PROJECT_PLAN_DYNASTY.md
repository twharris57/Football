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
priority, `SC` = Automated daily scout) — e.g. `RT-3`. Assigned once, in document order, and never reused
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
below): `NB-2`, `RT-31`, `VA-9`, `CQ-13`, `DL-9`, `SC-18`.

## Short list — actively prioritized right now

A small, hand-curated pointer into the backlog below — not a duplicate of
any item's content, just which `<SECTION>-<n>` tags are getting real
attention right now and why, so that's visible without reading the whole
file. Keep each tier to a handful of items; if either grows past ~5-6,
it's stopped being a "short" list — thin it back out to what's actually
active. Remove an item once it's done (its own full entry gets removed
too, per the convention above), don't let this become a history log.

**Initial-release build order** (revised 2026-09-13 — condensed to one
nightly `/schedule` routine that gathers, researches, decides, and
notifies end to end; see "Automated daily scout" below):

1. `scout-data` GitHub branch — the cloud routine's actual memory, since
   it has none of its own between runs. **Built, proven** (vertical-slice
   PoC, 2026-09-12/13).
2. `SC-1` — `gather_state()` runs inside the cloud routine's own sandbox.
   **Built.**
3. `SC-2` — templated finding schema. **Built.**
4. `SC-4` — run-record schema. **Built.**
5. `SC-17` — confirm a completed run doesn't auto-notify on its own.
   **Confirmed** (2026-09-17): a one-off `run_once_at` routine that made
   zero tool calls (no `PushNotification`, nothing else) produced no
   notification on the user's device. `SC-5`'s "stay quiet on a quiet
   night" guarantee holds.
6. `SC-18` — trade-block list as a checked-in file, so `SC-3` has
   something to read.
7. `SC-3` — Claude Scout research pass, bounded scope.
8. `SC-6` — the nightly orchestrator, tying `SC-1`/`SC-3`/`SC-4`/`SC-5`
   together and notifying.
9. `RT-21` — transaction log, pulled directly by the cloud routine.
10. `SC-7` — self-reflection pass against `RT-21`.

`SC-5`/`SC-8` are built alongside `SC-4`/`SC-3` rather than as separate
later steps — see their entries below. Target: once these land, schedule
the routine for 8pm local, fixed in-season cadence.

**Explicitly not required for initial release** (all still tracked
below, none block the list above): `SC-9` (season-aware ramp-up/throttle
— needed before next year's rookie draft, not before first ship), `SC-10`
(docs written incrementally; only the final consolidated pass waits),
and `SC-15`'s remaining NAS-side deployment (GitHub PAT, Task Scheduler
entry, backup coverage) — the `scout-data` branch itself is already in
the critical path above, but the NAS sync only ever feeds a future
dashboard, not the notify loop, so its deployment can wait until that
dashboard is actually being built. `SC-16`'s pruning ships inside `SC-6`;
its staleness banner waits on that same future dashboard.

**Nice to have (no deadline, worth doing when there's room):**

Empty right now — `RT-4` shipped 2026-08-29 (PR #67), `DL-7`/`DL-8`
shipped 2026-08-29 (PR #66).

## Current branch — fix before merge

Findings from reviewing the *active* branch's own not-yet-merged work —
kept separate from the thematic backlog below so "fix this before the PR
merges" is never mixed in with "someday" work. Ephemeral by design: cleared
out when the branch merges, not carried forward as history (the merged PR's
description is the historical record). A finding that gets explicitly
deferred rather than fixed moves down into the appropriate thematic section
below as a normal backlog item, same as any other deferred work.

Empty right now — cleared after PR #66 and PR #67 both merged
(2026-08-29/30). PR #67's finding (stale "phase is display-only" comments
in `power_timeline.py`/`roster_tab.py`) and PR #66's finding (DL-8 Phase
2's orphan-delete safety window being call-count-based rather than
wall-clock) were both fixed directly on their branches before merge; PR
#67's deferred methodology question (whether `PHASE_THRESHOLDS`'
calibration still holds up now that something acts on it) lives on as
`RT-30` below.

## Now — blocking

Empty right now — nothing blocking.

## Automated daily scout

Goal: catch dynasty opportunities (a depth-chart bump, an IR move that
frees a free agent, a trade window) on nights the user can't check in
personally — check automatically, stay quiet unless something's actually
worth acting on.

**Architecture: one nightly `/schedule` cloud routine does the whole
job.** Each run: gathers live Sleeper/FantasyCalc state (`SC-1`), runs
Scout's research pass (`SC-3`), checks results against its own history
(`SC-4`), applies materiality (`SC-5`), self-reflects (`SC-7`), notifies
via `PushNotification` when warranted, and commits updated state to the
`scout-data` GitHub branch (`SC-15`) — its only memory between runs. A
separate NAS job pulls that branch into local SQLite a few minutes
later, purely to feed a future dashboard; it is not on the notify path
and can lag or fail without consequence.

*Why GitHub, not the NAS, holds state:* an earlier design had the cloud
routine reach inbound to a NAS API. Two nights of live debugging
(2026-09-07) proved that's blocked at the network level regardless of
firewall/DNS/port config — outbound works fine both directions, inbound
never does. Don't revisit an inbound design here. (Checked against
`Finance-Dashboards`' similar "Claude scout" — different shape, raw
Anthropic API in a NAS container, no Claude Code routine, no push
notifications — not directly portable, but its dedup pattern informed
`SC-4`.)

- [ ] **SC-1: `gather_state()` runs inside the cloud routine's sandbox.**
  Built (`dynasty/scripts/daily_check.py`) — pulls Sleeper/FantasyCalc
  live, no NAS involved. Still open: the cloud environment's network
  allowlist needs `api.sleeper.app`, `api.fantasycalc.com`, `github.com`,
  `raw.githubusercontent.com` set manually on claude.ai. Also: nfl_data_py's
  cache never persists between runs, so every run pays its ~1-2 min
  cold-fetch cost — decide later whether to eat it or skip bye/scoring
  enrichment nightly.

- [ ] **SC-2: Finding schema.** Built (`dynasty/scout_api/finding_schema.py`
  + SQLite mirror) — fixed fields (player_id, category, summary, source,
  confidence, observed_at), no free text; this is the primary
  prompt-injection defense (`SC-8`). Still open: categories are
  first-draft guesses; nothing produces real findings yet (`SC-3`).

- [ ] **SC-3: Scout research pass.** Not started. Two tiers: (1) a cheap
  daily diff off structured data (`pickup_snapshots`, `RT-21`'s
  transaction log) to spot what changed; (2) real research only on what
  tier 1 or existing candidate-pool functions (free agent board, trade
  candidates, pickup alerts) already flagged, plus anyone on `SC-18`'s
  trade-block list — never a blind sweep. Writes `SC-2`-shaped findings.
  Build `SC-8`'s corroboration step in from the start, not after the fact.

- [ ] **SC-4: Run-record schema — dedup, materiality, and reflection
  state in one artifact.** Built (`dynasty/scout_api/run_record_schema.py`
  + SQLite mirror: `scout_run_records`/`scout_run_record_items`, indexed
  for dedup lookups on `(player_id, category)`). One `run_YYYYMMDD.json`
  per night in `scout-data`: what was reviewed, each item's surfaced/
  suppressed verdict and why, whether a notification fired, and a
  `reflection` slot reserved for `SC-7` to patch into a past run's file
  later (fetch/mutate/recommit — not implemented by this schema). Two
  verdict lanes: **deterministic** (numeric thresholds already used
  elsewhere — marginal value, FAAB comparables — real code, testable)
  and **agentic** (Scout's qualitative judgment, only after the
  deterministic dedup check already ran). Still open: nothing writes a
  real run record yet (`SC-6` does); the "only agentic, borderline
  verdicts go through `SC-8`'s corroboration search" rule isn't enforced
  anywhere yet since `SC-3` doesn't exist either.

- [ ] **SC-5: Materiality thresholds.** Consumes `SC-4`'s run records.
  Deterministic side reuses existing acceptance gates (`free_agent_board()`'s
  `> 0` marginal value, `suggested_trades()`'s tolerance gate), with
  `RT-10`/`RT-28`'s FAAB thin-sample caveat inherited explicitly.
  Convergence — a quantitative signal and a scout finding agreeing —
  is its own higher-confidence category, never blended into one score.

- [ ] **SC-6: Nightly orchestrator.** Not started — now mostly wiring,
  since `SC-4`'s schema carries the design weight. Orchestrates `SC-1` →
  `SC-3` → `SC-4`/`SC-5` → `SC-7` → notify → commit + prune (`SC-16`).
  Needs an explicit "checked, nothing new" vs. "check failed" status so
  a broken run never reads as a quiet night. Target cadence: 8pm local,
  in-season.

- [ ] **SC-7: Self-reflection.** Not started. Diffs `SC-4`'s recent run
  records against what actually happened, via `RT-21`'s transaction log.
  On a miss: identifies the cause, proposes a fix, opens a GitHub issue
  (never a direct commit/PR) with its own dedup so the same miss doesn't
  reopen nightly. Hard-blocked on `RT-21` existing — no ground truth to
  compare against otherwise. Falls back to writing the pending issue into
  `scout-data` if the cloud routine's GitHub access hiccups, flushed by a
  later run or the next local session.

- [ ] **SC-8: Prompt-injection defense.** Structural half already done via
  `SC-2`'s fixed-field schema. Remaining: a second, independent
  corroboration search before writing any borderline/high-stakes finding
  — build alongside `SC-3`, not retrofitted after.

- [ ] **SC-9: Season-aware cadence.** Not started, not needed for initial
  release — due before summer 2027. Fixed daily cron, gated internally on
  a live in-season/off-season signal (Sleeper's `league["status"]` and
  `settings.leg`), not a manually-flipped switch.

- [ ] **SC-10: Docs.** Not started. Write `docs/dynasty-daily-scout.md`
  incrementally as pieces land; final pass folds in this section's
  architecture notes once everything ships.

- [ ] **SC-15: `scout-data` GitHub branch + NAS-side sync
  (deprioritized).** The branch itself — the cloud routine's real
  memory — is built and proven (vertical-slice PoC, 2026-09-12/13):
  foundational, in the critical path. The NAS-side sync script
  (`dynasty/scout_api/sync.py`) is also built but **not deployed**, and
  no longer needs to be for the notify loop to work — it only ever feeds
  a future dashboard tab. Still open, whenever that dashboard is picked
  up: provision a GitHub PAT, wire a Synology Task Scheduler entry (with
  failure notification turned on), confirm the `scout_data` volume is
  backed up.

- [ ] **SC-16: 30-day retention pruning + staleness signal.** Not
  started. Pruning ships inside `SC-6`'s nightly commit-back step (keeps
  `scout-data` under GitHub's 1,000-entry listing cap). Staleness banner
  waits for a Scout UI to exist.

- [ ] **SC-18: Trade-block list — a checked-in file, not app state.**
  Not started. Sleeper has no "on the trade block" concept — which
  players are being shopped is purely user-declared intent, so it has to
  live somewhere the cloud routine can actually read. A small
  `trade_block.json` checked into `main`, edited directly by the user or
  a local Claude Code session (already has working git/`gh` write
  access, same capability `SC-7`'s fallback already leans on) rather
  than an automated NAS-to-GitHub push — trade-block changes are
  infrequent enough that this is simpler than giving the NAS app its own
  GitHub write credential. `SC-3` reads it to prioritize research.

**Build order:** `scout-data` branch ✅ → `SC-1` ✅ → `SC-2` ✅ → `SC-4` ✅
→ `SC-17` ✅ → `SC-18` → `SC-3` → `SC-6` → `RT-21` → `SC-7` → `SC-8`/`SC-9`
→ `SC-10`. `SC-15`'s remaining NAS deployment and `SC-16`'s staleness
banner are decoupled from this chain — pick up whenever a Scout UI is
built.

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
  general "does this team want more here" signal. `find_trade_offers()` is
  the first place `need_positions()` gets applied to someone *else's*
  roster to guess what they'd want, rather than the caller's own — a
  win-now partner might not care about "young core" at this position at
  all, or might specifically want to trade youth away for a proven
  veteran, the opposite of what the flag implies. The "need" flag itself
  is now phase-aware everywhere else it's read on a team's *own* roster
  (young-core while that team is rebuilding, VOR-based `weak` otherwise —
  see `roster_needs.py`'s `phase_aware_need_positions()`) — but
  `find_trade_offers()`'s tiebreaker was deliberately left calling the
  young-core-only `roster_needs_summary()` directly rather than converted,
  since a partner's own phase alone still might not answer this item's
  real question (a partner not running *any* rebuild strategy could
  contending-read as "roster-hole" and still not mean what a trade
  tiebreaker needs it to). Concrete next step if picked up: thread the
  partner's own `team_power_timeline` phase into `find_trade_offers()` and
  call `phase_aware_need_positions()` instead — low severity either way,
  since this is explicitly a ranking tiebreaker only (already noted in the
  function's own docstring, never the accept/reject gate).
- [ ] **RT-30: `PHASE_THRESHOLDS`' "revisit by feel" calibration now gates
  real recommendations, not just a display label — worth re-checking it's
  still an acceptable cutoff for that** (assistant valuation review,
  2026-08-29, PR #67) — `power_timeline.py`'s own comment on
  `PHASE_THRESHOLDS = (-0.3, 0.3)` says it was chosen "by feel" for a
  *display-only* phase label, explicitly stating downstream consumers
  should reason about the continuous `power_score` instead. PR #67 made
  `phase` itself decision-relevant for the first time: `need_positions`,
  `roster_value_analysis`'s drop-candidate `note`, and the draft plan's
  "flagged need" reasoning all now switch behavior at this exact boundary.
  This is the same shape as `valuation_principles.md`'s "dedicated-slot-only
  simplifications are fine for signals, not for action recommendations"
  rule, one level up: an already-accepted simplification tuned for a
  *display* bar (three-way visual bucketing, tolerant of imprecise
  boundaries since a user just reads a label) is now the actual switch
  behind three separate pieces of recommendation text. Nothing confirms
  the ±0.3 z-score cutoffs are still well-calibrated for that heavier use — a
  team sitting just inside one bucket by a hair (plausible in a 10-12 team
  league, where `power_score`'s std is well under 1 after averaging three
  z-scored components) gets a different "need"/"hold" read than an
  otherwise-identical team just across the line, with no hysteresis or
  buffer around the boundary. Concrete next step if picked up: either
  validate the current thresholds hold up under this use (e.g. check how
  often real teams sit within a small margin of ±0.3 across a season), or
  add a buffer band immediately around each threshold where `need`/`note`
  keep the *previous* phase's reading rather than flipping on a marginal
  crossing — low severity since `power_score` is shown alongside `phase`
  in the Roster tab (see PR #67's fix-before-merge item on the same
  branch), so a user reviewing a borderline case isn't flying fully blind.

  **Checked against real live data, 2026-08-30** (this league,
  `DEFAULT_LEAGUE_ID`, 12 teams): the concern is real, not hypothetical —
  6 of 12 teams currently sit within 0.2 of a `±0.3` boundary, 2 within
  0.1, against a league-wide `power_score` std of ~0.50. But this
  snapshot is itself incomplete: it's preseason, `games_played == 0`
  league-wide, so `win_pct_shrunk` is the identical neutral `0.5` for
  every team and contributes zero spread to `power_score` right now —
  once real records diverge, `power_score` will move more from week to
  week than today's number shows, if anything making a boundary flip more
  likely mid-season, not less. Given that, neither fix (validate the
  threshold / add a hysteresis buffer) is well-informed by a preseason-only
  read — user decision (2026-08-30): leave `PHASE_THRESHOLDS` and behavior
  unchanged for now, and re-run this same check (`team_power_timeline_scores()`'s
  `power_score` distribution vs. the ±0.3 boundary) once real win/loss
  records exist league-wide (a few weeks into the season, once
  `games_played > 0` for every team) before deciding between the two
  fixes with a representative sample. If a hysteresis buffer is the
  eventual choice, note it would add a new persisted-state layer (a
  per-team last-effective-phase cache, following `draft_snapshots.py`'s
  load/write pattern) to a module currently designed as "recomputed fresh
  every call... never cached" — a real architecture decision, not just a
  constant tweak, worth weighing against the cheaper "just widen the
  thresholds" alternative once real data is in hand.
- [ ] **RT-23: Suggested Trades - optional position-scope filter** (user-flagged
  2026-08-08, noted future option, not v1 scope, while building `RT-15`) —
  besides the single-target filter, also let the user scope leaguewide
  suggestions by position (e.g. "show me RB opportunities only") - a
  second, independent optional filter within the same section, not a
  replacement for the target filter. Not needed for the first cut; revisit
  now that leaguewide scanning itself is built and the section's filter UI
  exists to extend (see `docs/rookie-draft-big-board.md`'s "Suggested
  Trades" section).
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

  **Name confirmed, scope generalized (user-clarified 2026-09-03):** "Claude
  Scout" is the real name, and it's no longer only the on-demand, one-player
  lookup described above — `SC-3` (see "Automated daily scout" section
  below) builds it as a routine, scheduled research pass across the whole
  relevant player pool, writing findings to a persisted store the nightly
  `SC-6` routine reads. This item stays open specifically for the narrower
  "check this one named player right now" on-demand trigger, which may end
  up cheap to add on top of `SC-3`'s infrastructure once it exists rather
  than needing its own separate design — revisit once `SC-3` ships.
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

  **Promoted, 2026-09-03** — no longer just a next-draft revisit. `SC-7`'s
  self-reflection pass (see "Automated daily scout" below) needs exactly
  this endpoint: a reliable, timestamped, leaguewide record of what
  actually happened (adds/drops/IR moves), independent of this app's own
  refresh timing, to check the scout's prior output against. The
  leaguewide-visibility angle above is also now directly useful beyond the
  draft — it's what lets self-reflection notice a missed opportunity on
  *any* team's move, not just the user's own roster. Added to the short
  list alongside `SC-1`–`SC-6`; the unconfirmed assumptions above (cut
  transaction `type`, `leg` bucketing beyond a single observed value)
  still need live verification before implementation, same as before.
- [ ] **RT-31: Trade-block-style watchlist — track other teams' players
  worth a look, auto-remove once traded or dropped (user-flagged
  2026-09-03)** — periodically review who other managers have flagged as
  available (Sleeper's app-side "trade block"), add candidates to a
  tracked list for review, and drop them off it automatically once
  they're no longer relevant (rostered on a different team, or dropped
  outright — both already detectable via existing tooling, see below).
  **Checked live, 2026-09-03: Sleeper's public API does not expose trade
  block at all.** Confirmed two ways — this league's real
  `/league/{id}/rosters` response has no `trade_block`-shaped key
  anywhere in `metadata` (which is otherwise a real, populated free-form
  dict for this league, e.g. custom player nicknames — so it's not that
  metadata is empty/unused, trade block specifically isn't in it), and
  Sleeper's own API docs list only transactions/traded-picks/rosters as
  the trade-related surface, with no trade-block endpoint or field
  documented. So this can't be a Sleeper-sourced automated feed the way
  `RT-21`'s transaction log is — the "who's on the block" input has to
  come from somewhere else: most likely the user manually adding a
  player after seeing it mentioned in league chat/Discord/wherever
  trade-block talk actually happens in this league, not pulled from an
  API. Once a player's on the tracked list, though, removal *can* be
  fully automated — a rostered-elsewhere check (`rostered_player_ids`)
  or a dropped check (`pickup_snapshots.py`'s existing status diff)
  both already exist and are exactly what's needed, no new detection
  logic required there. Natural fit with this section's other work: a
  tracked player is a good candidate to feed into `SC-3`'s bounded scout
  scope (a manually-flagged player is at least as "earned attention" as
  one surfaced by the notable-events survey), and the list itself is
  another `SC-4`-shaped dedup/persistence problem, so this is worth
  scoping after `SC-2`'s store exists rather than as a standalone
  persistence design. Not part of the initial-release build order —
  files here as a real, scoped feature idea, not a vague "would be nice."
- [ ] **RT-25: Extend FAAB bid guidance to prior seasons via
  `previous_league_id`** (deliberately deferred from `RT-10`, 2026-08-20)
  — a real `previous_league_id` chain exists for this league and could
  substantially grow the comparable-bid sample beyond the current
  season's (still-thin, early-season) data. Two real complications
  user-flagged when this is picked up, not present in the current-season-
  only v1: **(1) league membership churn** — a `roster_id`/owner from a
  prior season may no longer be in the league (or a current owner may not
  have been), so pulling in their historical bids without accounting for
  that risks calibrating guidance partly on bidding behavior from people
  who aren't part of this negotiation anymore, or missing a real member's
  history if they joined more recently; needs the real owner/roster
  mapping checked per season, not assumed stable. **(2) recency bias** —
  older bids should count for less than recent ones (both because FAAB
  budgets/behavior can drift year to year, and because `won_bid_sample`
  already uses *current* `adj_value` as a proxy for a player's value at
  bid time — see `docs/rookie-draft-big-board.md`'s "Static assumptions"
  table — a proxy that gets progressively less accurate the further back
  a comparable bid is from).
  A weighted-by-recency sample (or a hard recency window) is likely
  needed, not a flat pool across all available seasons.
- [ ] **RT-26: Draft Board — a year selector, defaulting to the current
  year** (user-flagged 2026-08-20, future years) — once more than one
  rookie draft's worth of history exists, add a dropdown to the Draft
  Board tab (defaulting to the current/most-recent year) that lets the
  user look back at a prior year's board instead of only ever showing the
  latest. Not urgent yet (only one draft has happened so far) — revisit
  once a second season's draft data exists to actually browse back to.

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

## Code quality, tests & UX polish

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
- [ ] **CQ-13: Summary tab's "(+N more)" note has nowhere to send the user**
  (user-flagged 2026-09-03, seen live as "and 7 others") — `summary.py`'s
  `_capped()` caps each Attention Digest category to `top_n=3` and appends
  a plain-text `"(+N more)"` line (`summary_tab.py` renders it as an
  ordinary `st.caption`, no link, no expander), so a user seeing "(+7
  more)" has no way to find out what the other 7 are or where to look.
  Three of the four capped categories (`weekly_gaps`, `sellable`,
  `free_agents`) do have a fuller view elsewhere (Roster tab), so the fix
  there is straightforward — point the note at the right tab. The fourth,
  `pickup_alerts`, doesn't: grepped the whole `tabs/` package and it's
  rendered *only* in `summary_tab.py` — there is no other view of the
  full pickup-alert list to send anyone to yet, so fixing this category
  needs a real full-list view built first, not just a better link.
  Directly relevant to this section, not just a coincidental UX bug: `SC-6`'s
  push notification is going to face the identical "here's the top few,
  and N more" shape, and would hit the exact same dead end if it doesn't
  give the user somewhere to go — this is exactly what `SC-2`'s store
  (mirrored into the NAS-side SQLite `SC-15` maintains, or eventually a
  dedicated view in the app) is positioned to be, so treat this old bug
  as an early warning for that design, not a separate concern to fix in
  isolation later.
- [ ] **CQ-8: Add signal handlers for graceful container shutdown**
  (user-flagged 2026-08-20) — `docker_guidelines.md`'s existing "Graceful
  Shutdown" section already covers half of this (`CMD` exec form so
  signals reach the process at all, confirmed already true for this
  repo's `Dockerfile`), but doesn't yet say anything about the *process
  itself* handling `SIGTERM` and shutting down cleanly within the
  orchestrator's grace period once it receives one. Likely belongs as an
  addition to that same convention section — but `docker_guidelines.md`
  may be AgentConfig-sourced (shared across projects, pulled via
  `/update-from-agentconfig`) rather than owned directly by this repo, so
  the fix might need to flow through AgentConfig rather than a direct
  edit here; confirm which before implementing. Deliberately deferred to
  its own branch, not bundled into unrelated work.

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
