# Valuation Principles

Durable rules for how player/pick/roster value is computed in the dynasty
tools (`dynasty/dynasty_core/`, `dynasty/player_scoring.py`, `dynasty/fantasycalc_api.py`). This
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

`gather_state`'s `data_warnings` list exists so a fallback (byes, handcuffs,
scoring multipliers) is visible to the user rather than indistinguishable
from "nothing to report." `pick_trade_values()` (2026-08-01 review) has the
same silent-fallback risk (a FantasyCalc naming change would blank every
`value`) and its docstring says so — but nothing populates `data_warnings`
when it happens.

**The rule**: a comment describing a silent-degradation risk isn't a
substitute for wiring it into `data_warnings`. If a computation can
quietly produce an empty/degraded result on a join or format mismatch, add
the cheap check and append to `data_warnings` at the point of degradation
— the pattern every other fallback in `gather_state` already uses.

**A bare `value or default` doesn't catch `NaN`.** `find_trade_offers()`
(RT-12, 2026-08-02 review) resolved a target's value with
`pick_value_by_name.get(...) or 0.0`, meant to normalize a missing/`None`
lookup — but `NaN` is truthy in Python, so an unresolved-but-present value
(the same pick-naming gap above) passed through as `NaN`, not `0.0`, and
then silently defeated every downstream comparison (`max(nan, x)` and any
`<`/`>` against `NaN` behave unpredictably) — a hard acceptance gate quietly
became a no-op instead of erroring.

**The rule**: never normalize a possibly-missing numeric value with a bare
`value or default` if the source can produce `NaN` (any `pandas`/`numpy`
column with unresolved joins). Use `pd.isna(value)` explicitly instead —
`NaN` slides past `or` unchanged and silently short-circuits every
comparison it touches. Sharper-edged than the general rule above: a plain
`None`/`0.0` at least fails loud-ish; an unnoticed `NaN` can make a gate
stop functioning altogether.

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

`recommend_drop()`'s `exclude_ids` (RT-13, 2026-08-02 review) is meant to
protect specific players from being *chosen* as the recommended cut, but
filtered them out of `rows` *before* `assign_starters()` ran — removing
them from the starter competition entirely, not just the cut-eligible
pool. Since removing a competitor can only ever help the remaining
candidates win a slot, an existing droppable player could read as
`is_starter: True` when they'd actually be bench on the real roster — an
error that only ever overstates a cut's severity, surfaced once
`evaluate_trade()` made `exclude_ids` non-empty on nearly every call.

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

## Every `assign_starters()` call needs the same `ineligible_ids` filter, not just the established ones

`recommend_drop()` and `best_position_relevant_drop()` (both in
`marginal_value.py`) both filter taxi/IR players out of their rows before
calling `assign_starters()` — documented inline as "Sleeper doesn't allow
it," since a taxi/IR player can never actually occupy a starting slot.
`draft_plan.py`'s new `"confirmed"` `drop_status` branch (`RT-20`,
2026-08-07 review) added a third `is_starter` computation for a
draft-plan round's recovered real drop — `assign_starters()` on
`player_value_rows(hypothetical_ids, ...)` — and skipped the filter,
because it was written as new inline logic rather than by reusing (or
even glancing at) the two existing call sites. A taxi-stashed player —
this league's normal roster state under its rebuild strategy — can then
win a starting slot in that computation and bump a real starter onto the
"bench" side of the result, so a genuinely-dropped starter can silently
read as `is_starter: False`. Not caught by the new tests, since none of
them constructed a roster with a non-empty `taxi`/`reserve` list.

**The rule**: `assign_starters()` must never be called on a roster's raw
`player_value_rows()` output directly — taxi/IR occupants are never
eligible for a starting slot, and the established pattern is
`[r for r in rows if r["player_id"] not in ineligible_ids]` before the
call, every time. Before writing a new inline `is_starter`/starter-set
computation anywhere in this codebase, check whether `recommend_drop()`
or `best_position_relevant_drop()` already does what's needed — this is
the same shape as this file's "one valuation strategy, used everywhere"
rule, specifically for starter assignment: a parallel `assign_starters()`
call site is a second implementation of "who's starting," not a new
question, and it will silently drift from the established one the moment
it forgets a filter the others already carry.

## A composite label needs a parser that handles every format its own source can produce

`_pick_context_callouts()` (`trade.py`, RT-18, 2026-08-07 review) derived a
traded pick's season/class by splitting its display name on the literal
substring `" Pick "` — correct for `pick_trade_values()`'s current-season
name format (`"2026 Pick 1.01"`), but that same function also emits a
structurally different next-season format with no `" Pick "` substring at
all (`"2027 1st"`, built from `ROUND_ORDINAL`, since there's no real draft
slot to name a future pick by yet). Splitting on an absent substring
returns the original string untouched, so every next-season pick's
"season" silently became its own full pick name — not an exception, not
an empty result, just a wrong-but-plausible-looking one: every next-season
pick always ranked `#1` in a one-member "class" whose printed label was
the garbled pick name instead of a year. The bug was invisible in review
because the one new test exercised only the current-season format the
code was written against, never the next-season format the same producer
function also emits.

**The rule**: when a field is a formatted display string produced by a
function that itself emits more than one shape for different inputs (a
per-slot name this season vs. a per-round name next season; a singular vs.
plural label; an abbreviated vs. full form), parsing code downstream must
be checked against every shape that producer can emit, not just the shape
the immediate use case happened to be written against. Trace the value
back to where it's constructed — here, `pick_trade_values()`'s two
separate `rows.append()` blocks, one per season — and check each branch,
not just the one the new code's own test picked. Prefer parsing on a
stable, format-independent anchor (a leading year, a delimiter guaranteed
present in every format) over a substring that only some formats actually
contain.

The anchor-based parse above is the immediate fix; the sturdier version is
not parsing at all downstream. If a value's structure (a pick's
season/round) is already known at the point its display label is built,
attach it as its own field there and have every consumer read the field —
never re-derive it from the label later, where each call site can (and
here, already did) get the derivation subtly wrong in its own way. Tracked
as a deferred cleanup, `CQ-5` in `.claude/PROJECT_PLAN.md`.

## A "right now" list needs to anchor on the live current week, not raw order

`build_attention_digest()`'s weekly-gap line (`summary.py`, RT-19,
2026-08-08 review) lists `roster_weekly_gaps` gap weeks in the same order
`roster_weekly_gaps()` already produces them — week 1..18 — then caps to
`top_n`. That order is fine for `roster_tab.py`'s full 18-week reference
table, where nothing is hidden and the user reads week numbers directly.
It's wrong for a capped "what needs attention right now" digest: a week
that's already happened has nothing left to act on, but nothing stopped it
from filling one of the few capped slots ahead of a real upcoming week,
which then never appears at all. The project already has the right tool
for "already happened vs. still ahead" — `league["settings"]["leg"]`
(Sleeper's current-week counter), used by `roster_tab.py`'s
`_render_bye_impact()` for exactly this distinction — it just wasn't
threaded into the new digest.

**The rule**: any user-facing summary that presents a short, *capped* list
of time-scoped items (weekly gaps, bye conflicts, deadlines, anything
keyed by NFL week) must filter or sort by proximity to the live
current-week counter before capping, not by the item's raw storage order.
An uncapped reference table showing the same data in the same raw order is
fine — the failure only appears once truncation enters the picture, because
that's the point past-relevance stops being harmless and starts silently
displacing something actionable. Recognize this shape wherever a new
feature caps or ranks a list built from week-indexed data (the planned
`RT-9` free-agent monitor is a likely next case) — check whether "current
week" needs to be a parameter before the list is capped, the same way
`roster_tab.py` already had to for its own bye-impact view.

## "First time seen in this narrower pool" is not "first time this ever happened"

`pickup_snapshots._diff()` (RT-9, 2026-08-08 review) treats a player
absent from the tracked snapshot as a "just signed with {team}" event —
correct when the player is genuinely new to Sleeper's NFL player data
(a rookie signing their first contract, a true free-agent signing after
being teamless). But the snapshot only ever tracks `free_agent_pool()`'s
membership — anyone currently on a fantasy roster is excluded from it
entirely. So the dominant real-world way a veteran gets a `prior is None`
entry isn't a new NFL signing at all: it's a fantasy manager dropping them
mid-season, while they've sat on the same real NFL roster the whole time.
The diff can't tell these apart, because it was never given the
information to — it only ever saw the narrower, fantasy-roster-filtered
pool, never the player's real attribute history independent of that
filter. The result is a plausible-looking, wrong causal claim ("just
signed with the Chiefs" for a three-year Chiefs veteran) presented as fact
in an alert meant to prompt a real roster action — the same shape as
`valuation_principles.md`'s "composite label" rule (RT-18), but the
mismatch here is between two different *populations* being silently
treated as one, not two string formats.

**The rule**: before treating "no entry in a tracked/cached history" as
"this is the first time this attribute-holder has ever had this
attribute" (a signing, a status change, a first appearance), check whether
the tracked population is itself a filtered subset of the real-world
population the claim is about. If a member can leave and re-enter the
*tracked subset* for reasons that have nothing to do with the attribute
being diffed (here: fantasy-roster status, unrelated to real NFL-team
status), a first sighting in the subset is not evidence of a first
real-world occurrence — it's only evidence of a first sighting *within
that filter*. Either track the broader unfiltered population so a real
baseline exists regardless of subset membership (alerting can still stay
scoped to the narrower, actionable subset), or weaken the claim to what
the data actually supports ("newly available" rather than "just signed")
when no real prior baseline exists.

## A "worth surfacing" filter applied at an early ranking stage must be re-applied at whichever stage actually presents the recommendation

`leaguewide_trade_candidates()` (Stage 1 of Suggested Trades, RT-15,
2026-08-08 review) correctly filters its leaguewide player pool to
`marginal_value > 0` before ranking — matching `free_agent_board`'s and
`pickup_alerts`' existing "worth surfacing at all" convention (see this
file's own reuse pattern). But `suggested_trades()` (Stage 2 — the
function that actually runs the real offer search and hands the UI what
gets shown as a "Suggested Trade") drops that standard: it only requires
`find_trade_offers()` to return a non-empty `offers` list — some combo
cleared the *partner's* plausibility bar — then sorts survivors by
`your_side["lineup_delta_after_drops"]` and shows the top 3 with no floor
at zero. A candidate whose only viable offer is net-neutral, or actually
negative, for the user's own lineup can still be ranked and presented as
a "Suggested Trade" — proven by the branch's own new test, which
constructs exactly this (`target_a`'s only offer has
`lineup_delta_after_drops == 0.0`) and asserts it survives into the
result list rather than being dropped.

This is a materially bigger problem for Stage 2 than it would have been
for the manual, single-target trade-target optimizer this feature
replaced: there, a human always saw one target's own `target_read`
("worth pursuing," computed for free before any search ran) and decided
for themselves whether to even run the offer search. Suggested Trades
removes that human checkpoint by design — it auto-selects candidates and
auto-presents ranked results as the feature's whole value proposition —
which is exactly why the filter Stage 1 already enforces needs to survive
into Stage 2's own output, not just gate which candidates get the
expensive search.

**The rule**: when a multi-stage ranking pipeline has an earlier stage
that filters to "worth surfacing" (a positivity check, a floor, any
"don't show this at all" gate), don't assume that filter's effect
automatically carries through to a later stage that re-ranks or
re-derives its own output metric — check explicitly. This is easiest to
miss exactly when the later stage's ranking key differs from the earlier
stage's filtered field (here: Stage 1 filters `marginal_value`, Stage 2
ranks by the differently-computed `lineup_delta_after_drops`), since nothing
about reusing the earlier stage's *candidates* guarantees the later
stage's *own number* stays positive too. The risk is highest, and the bar
for catching it should be highest, precisely where a pipeline stage
removes a human review step earlier stages relied on — automating "pick
and present" is what turns a merely-imprecise signal into a wrong action
recommendation a user might actually act on.
