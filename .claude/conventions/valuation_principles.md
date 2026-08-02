# Valuation Principles

Durable rules for how player/pick/roster value is computed in the dynasty
tools (`dynasty_core.py`, `player_scoring.py`, `fantasycalc_api.py`). This
file is the *rules to follow* when extending or changing that logic — see
`docs/rookie-draft-big-board.md` for the current methodology itself, and
`.claude/PROJECT_PLAN.md` for what's still open. Grew out of a 2026-07-31
valuation review; keep it updated as the methodology evolves rather than
letting it drift into a historical snapshot.

## One valuation strategy, used everywhere

Never let two different features answer "how good is this player/roster"
with two different algorithms. This project already hit this failure mode
once: an earlier "Strategy" tab computed a single top-pick recommendation
with a *different* algorithm than the round-by-round Draft Plan, and the two
disagreed with each other on live data — not a feature, a bug. It was fixed
by deleting the second algorithm, not reconciling the two (see
`docs/dynasty-draft-web-app.md`).

When a new feature needs "is this player/pick/roster good," reuse the
existing ranking primitives (`rank_by_marginal_value`,
`positional_strength_summary`'s `vor`, `season_average_starter_value`) by
composition, rather than inventing a parallel scoring path — even a
simpler one, and even for a narrower question. If an existing primitive
doesn't fit, that's a signal to extend it, not to bolt on a second one next
to it.

## Superflex inflates QB value — model it as such, everywhere

This is a confirmed superflex league (`SUPER_FLEX` is a real slot in
`roster_positions`). In a superflex format, roughly two QBs per team are
startable, not one — QB scarcity is a bigger value driver here than in a
standard single-QB league, and any positional-value logic that quietly
assumes single-QB demand will misjudge QB specifically, which is the
position this league's scarcity premium depends on getting right.

- The **market-value layer already gets this right**: `num_qbs` (passed to
  `fantasycalc.get_dynasty_values()`) is `roster_positions.count("QB") +
  roster_positions.count("SUPER_FLEX")`, not just the dedicated count.
- Any **home-grown positional-value logic built on top of the market
  value** (replacement level, VOR, the power/timeline read, "sellable
  vs. droppable" thresholds) needs to carry the same superflex-aware demand
  through, not just count dedicated slots. `position_replacement_levels()`
  originally didn't do this — fixed via `_position_starter_demand()` (see
  `dynasty_core.py`) — treat that as the reference example of the failure
  mode to avoid next time, not a one-off bug.
- More generally: whenever a metric here needs "how many players are
  really demanded at this position," start from `roster_positions` and
  include `FLEX`/`SUPER_FLEX` eligibility, not just the position's own
  dedicated slot count — the dedicated-only shortcut is a known, currently
  live simplification in a few places (`roster_weekly_gaps`,
  `position_replacement_levels`), not a pattern to extend on purpose.

## Dedicated-slot-only simplifications are fine for signals, not for action recommendations

`_position_starter_demand()` deliberately doesn't count `FLEX` demand for
RB/WR/TE (unlike `SUPER_FLEX` for QB, above) — FLEX splits demand across
three positions with no similarly clean allocation, so this was accepted
as a known, documented gap. That was a reasonable call *while* every
consumer of it was an informational signal (`vor`, `weak`) that a human
reads and interprets themselves.

It stopped being harmless the moment a feature started **acting** on it
directly: `sellable_players()` (2026-08-01 valuation review) uses the same
dedicated-slot-only `starter_count` to decide which players are "starters"
(protected) versus "depth" (surfaced as sellable) — and a position's real
FLEX starter can land on the wrong side of that line, since neither that
count nor `gap_delta`'s weekly-gap check (same dedicated-slot-only gap)
catches it. The result isn't a slightly-off number, it's a concrete wrong
recommendation someone could act on.

**The rule**: before reusing a dedicated-slot-only signal (or any other
already-accepted simplification) as the basis for something that
recommends an action — sell, drop, add, start/sit — re-examine whether the
simplification's error rate is still acceptable for that specific use.
"Fine for a VOR number a human eyeballs" and "fine for a list titled
'sellable'" are different bars. When in doubt, name the gap explicitly in
the new feature's own docstring rather than assuming the original
docstring's caveat still covers it.

## Treat external IDs as opaque keys, not ranges

Sleeper's `roster_id`, `player_id`/`sleeper_id`, and similar identifiers
are keys to look up, never a range or order to iterate — this project
already gets this right almost everywhere (`rosters_by_id`,
`roster_capacity`, `fc_by_sleeper_id`, all keyed lookups over the real
`rosters`/`players` data, never a synthesized range). `_future_pick_owners`
(2026-08-01 valuation review) was the first exception:
`for roster_id in range(1, num_teams + 1)` assumes `roster_id` is exactly
`1..num_teams`, contiguous, no gaps — true for this league by Sleeper's
normal convention, but never verified, and nothing else in the codebase
relies on that convention holding.

**The rule**: if a computation needs "every team," iterate the real
`rosters` list (or another real collection already pulled from the API)
and read `roster_id` off of it — don't synthesize an integer range and
assume it lines up. If there's ever a genuine reason to assume an ID space
is contiguous, verify it against live data first and document the
assumption in `docs/rookie-draft-big-board.md`'s "Static assumptions"
table, the same as any other unverified constant.

## Silent data-degradation must surface as a warning, not just a comment

`gather_state`'s `data_warnings` list exists specifically so a fallback —
byes, handcuffs, and the scoring multipliers all use it — is visible to
the user instead of being indistinguishable from "there's nothing to
report." `pick_trade_values()` (2026-08-01 valuation review) has the same
kind of silent-fallback risk (a FantasyCalc pick-naming convention change
would leave every `value` blank, no exception raised) and its docstring
even says so — but nothing actually populates `data_warnings` when it
happens, unlike every other fallback path in this file.

**The rule**: a well-written comment describing a silent-degradation risk
is not a substitute for wiring it into `data_warnings`. If a computation
can quietly produce an empty/degraded result on a join, name-match, or
external-format mismatch, add the cheap check (`if result.isna().all(): ...`
or equivalent) and append to `data_warnings` at the point the degradation
is detected — the same pattern already established for every other
data-dependent enrichment step in `gather_state`, not a new one to invent.

## Prefer real scoring rules pulled live over hardcoding — document what you can't

When a computed value depends on this league's scoring format, prefer
deriving it from the live `league["scoring_settings"]` (or another value
already threaded through from a live API response) over hardcoding a
number. The project already does this well in most places — `roster_positions`,
`taxi_slots`, `scoring_settings`, `num_teams`, PPR, and superflex count are
all pulled fresh every refresh specifically so a commissioner settings
change doesn't require a code change (see `docs/rookie-draft-big-board.md`'s
"Static assumptions" table).

Where there's genuinely no live source — FantasyCalc doesn't publish its
own scoring formula, so `player_scoring.BASELINE_SCORING` has to be an
explicit guess — hardcoding is fine, **provided it's documented**: state the
assumption in a comment at its definition, add a row to the "Static
assumptions" table naming what breaks if it's wrong and how to revisit it,
and keep the raw/unadjusted value available alongside the corrected one so
the correction's effect stays visible and reversible (`value` next to
`adj_value`, not `adj_value` overwriting `value`). `POSITION_VALUE_MULTIPLIER`
is the model example of this pattern's full lifecycle: hardcoded by
necessity at first, documented as a last-resort fallback the whole time,
and superseded by a live-derivable per-player computation
(`player_scoring.py`) once one became feasible — not silently, the doc and
the plan both tracked the transition.

Before trusting a hardcoded value as harmless, check whether it's coupled
to something that *is* pulled live elsewhere in the same computation — a
hardcoded number that happens to match today's live value can silently stop
matching if that live value ever changes (see `BASELINE_SCORING`'s `rec: 1.0`
vs. the real `ppr` param sent to FantasyCalc, `.claude/PROJECT_PLAN.md`'s
`VA-2`, found only because this happened to be audited, not because
anything would have failed loudly).

## A field used as both an internal score input and a user-facing label needs two names

`_shrunk_win_pct()` (RT-1, 2026-08-02) blends a team's real win/loss record
toward a neutral `0.5` prior for small-sample-size reasons — correct for
its one actual consumer, `power_score`'s z-scoring. But it overwrote the
`win_pct` column that `team_power_timeline_scores()` already exposed, and
that same column is what `rookie_draft.py`/`streamlit_app.py` print
verbatim next to the literal label "Win %" — a 1-0 team now shows "60%"
where its real record is 100%, with no visible indication the number
isn't the record.

This is the same shape of mistake as the raw/`adj_value` rule above — keep
the corrected value next to the raw one rather than overwriting it — but
it surfaced through a statistical correction instead of a hardcoded
constant, on a field a UI was already printing verbatim under a label
that promises the raw value. The correction itself wasn't wrong;
routing it through the same column name the display path already trusted
was.

**The rule**: before applying a transform (shrinkage, smoothing, clipping,
a market-value correction) to a field, check every existing consumer of
that field's name, not just the one motivating the change. If any
consumer expects the untransformed value — especially a display label
that names the field literally ("Win %", "Value", "Rank") — expose both
under distinct names rather than letting one name's meaning silently
depend on which caller reads it.

## Mutually exclusive candidate pools must derive from each other's membership

This project has several "candidate pool" functions that enumerate a slice
of the same underlying player universe — `rookie_pool()` (this year's
class), `free_agent_pool()` (every non-rostered player), `available`
(rookies not yet drafted this session). Some of these are supposed to be
mutually exclusive in the real world even when nothing in the data forces
it: a player can't simultaneously be "available to draft" and "available to
add off waivers." `free_agent_pool()` (RT-3, 2026-08-02) computed its
membership independently of the rookie-draft pool — checking only
`rostered_player_ids` — so a rookie still in this league's active startup
draft (real NFL `team` set, not yet on any fantasy roster, so not excluded
by anything `free_agent_pool()` checked) showed up on the Free agents board
as a waiver-wire add, when the only real way to acquire them was the
draft in progress. Caught live (a specific rookie visibly on both boards at
once), not by the test suite — `TestFreeAgentPool`/`TestFreeAgentBoard`
never constructed a pending-draft rookie in the candidate pool, only
rostered/no-team/non-fantasy-position exclusions.

Fixed by threading the draft's own `available` pool into `free_agent_pool()`
as an explicit `draft_eligible_rookie_ids` exclusion, gated on whether the
startup draft still has picks remaining — not a second, independent
rookie-eligibility check, reusing the one `gather_state` already computes.

**The rule**: when two candidate-pool functions are supposed to be
mutually exclusive in reality (draftable vs. addable, sellable vs.
protected, etc.), don't let each compute membership solely from its own
"what excludes you" checklist against the raw player universe. Have the
narrower/more-temporary pool (here, "still draftable this session") flow
into the other's exclusion set explicitly, and re-check whenever a new
candidate-pool feature is added whether it overlaps an existing one's
real-world exclusivity window. Test coverage for a candidate-pool function
should include at least one case from every *other* pool that's supposed to
be mutually exclusive with it, not just the pool's own internal exclusion
rules.

## A capacity ceiling that restricts new entrants must not also erase credit for room already spent

`roster_total_capacity()`'s `taxi_eligible` flag is meant to answer one
narrow question: can a *new* player (a free-agent add, or the incoming
side of a trade) land on an open taxi slot? `free_agent_board()` and
`evaluate_trade()` (RT-2, 2026-08-02 review, see `.claude/PROJECT_PLAN.md`'s
fix-before-merge section and `RT-11`) both pass `taxi_eligible=False` for
veteran candidates — correctly refusing to count an *unused* taxi slot as
room for them. But the same flag also zeroes `taxi_slots` out of the
capacity total entirely, which silently strips credit for taxi slots the
roster *already* has filled. Those existing occupants (almost always
stashed rookies — the normal state for this league's rebuild strategy, not
an exception) are still legitimately off the active/bench headcount and
have nothing to do with the candidate/trade being evaluated. The result: a
roster carrying even one taxi player can read as needing a forced drop, or
flag `over_capacity`, when it actually has open bench room.

Contrast with `reserve_filled`, which gets this right: it's an
always-applied headcount of currently-occupied IR slots, never gated by an
eligibility flag, precisely because "can a new player use this" and "is
this already spoken for" are different questions. `taxi_slots` collapsed
both questions into one flag.

**The rule**: a flag that gates whether a *new* entrant may use a category
of slot is not the same as whether *existing* occupants of that category
should still count as consumed capacity. When adding an eligibility gate
for future use of a resource, keep a separate, always-on credit for
capacity already spent by current occupants — don't let disabling future
eligibility also zero out the accounting for the past. Watch for this
shape elsewhere: anywhere "is there room for X" is modeled by zeroing an
entire slot category's *capacity* rather than just closing off further
*entry* into it.

## Exclusion filters change the outcome for everyone else, not just the excluded entity

`recommend_drop()`'s `exclude_ids` parameter is meant to protect specific
players from being *chosen* as the recommended cut (earlier-round draft
picks in `multi_round_plan`'s `exclude_from_drop`; a trade's own incoming
players in `evaluate_trade()`'s new `recommended_drops`, RT-13,
2026-08-02 review). But it filters those players out of `rows` *before*
`assign_starters()` runs — removing them from the competition used to
decide who counts as a "starter" at all, not just from the pool of
candidates eligible to be cut. Removing a competitor can only ever help
the remaining candidates win a slot, never hurt them, so an existing
droppable player can read as `is_starter: True` when, in the real roster
(protected players correctly seated), they'd actually be bench. The
reverse can't happen — a real starter never gets mislabeled bench by this
mechanism — so the error only ever overstates a cut's severity. Live in
`recommend_drop()` since before this review, but only a rare edge case
until `evaluate_trade()` made `exclude_ids` non-empty on essentially every
call and started surfacing `is_starter` as a direct user-facing warning
tag rather than an internal comparison.

**The rule**: "protect this entity from being selected" and "remove this
entity from the field" are different operations. A filter meant only to
protect a candidate from being *chosen* by a downstream ranking/assignment
step must still let that candidate *participate* in whatever competitive
step determines outcomes for everyone else — otherwise every other
participant's computed status (starter/bench, winner/loser, eligible/
ineligible) is quietly computed against a smaller field than reality.
Apply the exclusion at the final selection step, not by stripping the
candidate out of the shared computation upstream of it. Watch for this
shape wherever a "protect X from Y" parameter is implemented as "delete X
before computing Y," rather than "compute Y normally, then skip X when Y's
result is applied."
