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
  value** (replacement level, VOR, a future power/timeline read, "sellable
  vs. droppable" thresholds) needs to carry the same superflex-aware demand
  through, not just count dedicated slots. `position_replacement_levels()`
  currently does *not* do this (tracked in `.claude/PROJECT_PLAN.md`,
  Roster & trade tooling item 1) — treat that as the reference example of
  the failure mode to avoid next time, not a one-off bug.
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
vs. the real `ppr` param sent to FantasyCalc, `.claude/PROJECT_PLAN.md`
Valuation & data accuracy item 2, found only because this happened to be
audited, not because anything would have failed loudly).
