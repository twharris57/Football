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
