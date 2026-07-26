# Rookie Draft Big Board — Logic & Methodology

What `dynasty_core.py` computes: a full analysis of the user's Sleeper dynasty
league (id `1324888291937386496`, "Dynasty Degenerates") ahead of and during
the rookie draft — who to pick, who to drop, and what that does to the roster
across a season. Consumed by both `rookie_draft.py` (CLI) and `streamlit_app.py`
(web dashboard); see `docs/dynasty-draft-web-app.md` for the presentation layer.

## Data sources

| Source | What it provides |
|---|---|
| Sleeper API (`sleeper_api.py`) | League settings/scoring, rosters, users, draft state, live picks, traded picks, and the full player reference dataset (cached to disk, 12h TTL — it's ~14MB) |
| FantasyCalc (`fantasycalc_api.py`) | Dynasty trade values — the only valuation source; this project has no model of its own for absolute player value |
| `nfl_data_py` | NFL schedules (bye weeks) and depth charts (handcuffs) — both public, free, and already a project dependency |

## Valuation: market baseline + a targeted correction, not a full model

FantasyCalc's API only exposes three knobs: superflex (`numQbs`), league size,
and PPR. It has no parameter for this league's two biggest scoring departures
from a generic model:

- **6-point passing touchdowns** instead of the far more common 4-point.
- **TE premium**: +0.5 per reception for tight ends, on top of full PPR.

`POSITION_VALUE_MULTIPLIER` (`QB: 1.164`, `TE: 1.204`) corrects for exactly
these two gaps. The numbers are **computed, not guessed**: pulled from real
2024 season stats (the most recent complete season `nfl_data_py` has
published — 2025 isn't out yet), as the ratio of total fantasy points under
this league's real rule vs. FantasyCalc's assumed baseline, holding every
other scoring setting constant, for startable-volume players (QB: ≥200
attempts, 39 qualifying; TE: ≥30 targets, 45 qualifying). `adjusted_value()`
applies it; the raw FantasyCalc `value` is kept alongside everywhere for
comparison, not overwritten.

**Not corrected**, and stated as such wherever it's relevant: smaller bonuses
for long touchdowns (40+/50+ yard) and first downs (`rush_fd`/`rec_fd`) —
present in this league's scoring but not isolated the way the two big ones
were. A real per-player recompute from raw stats (a further-out project idea,
not built) would replace this whole correction with something exact.

## Ranking: marginal lineup value, not raw trade value

The draft plan does **not** rank candidates by `adj_value`. It ranks by how
much drafting a candidate would raise the roster's **season-average optimal
starting-lineup value** — the value-over-replacement question a draft
decision actually is, not "who has the highest card value." A modestly
valued player at a genuinely thin position can outrank a highly valued one
who wouldn't even crack the starting lineup.

- **`assign_starters()`** fills starting slots most-restrictive-first:
  dedicated QB/RB/WR/TE, then FLEX (RB/WR/TE eligible), then SUPER_FLEX
  (any of the four). This is provably optimal for this league's *nested*
  slot eligibility (QB's dedicated slot ⊂ SUPER_FLEX's eligible set;
  RB/WR/TE dedicated ⊂ FLEX's ⊂ SUPER_FLEX's) — a standard greedy exchange
  argument, not just a heuristic. Verified against real output: a second
  startable QB correctly wins the SUPER_FLEX slot over bench WRs.
- **`season_average_starter_value()`** runs that assignment separately for
  each of the 18 NFL weeks, excluding players on bye that week, and averages
  the total across the season. Every player misses exactly one week (their
  own bye), so this doesn't inherently favor or penalize anyone for having a
  bye at all — what it captures correctly is the *interaction*: a pickup
  whose bye lines up with an already-thin position contributes less across a
  season than the same value somewhere with real depth behind it. Weekly-gap
  *detection* is a separate, dedicated feature (`roster_weekly_gaps`) — this
  is about getting the season-long value comparison right, not re-deriving
  gap alerts.
- **`rank_by_marginal_value()`** ties it together: for each candidate,
  simulate adding them (and making the resulting recommended drop), and
  measure the season-average delta. Confirmed this reorders picks in a real,
  non-trivial way against a pure-value baseline — one simulated round
  correctly passed on a top-3 raw-value QB in favor of a lower-value WR who
  was the better marginal fit for the roster at that point in the plan.

`recommend_drop()` feeds the drop side: lowest-value **bench** player,
preferred over starters (via the same `assign_starters` assignment) — a
marginal starter isn't recommended for cut over a similarly valued deep
bench piece.

## Features

- **Rookie big board** — the whole rookie class, not just what's left.
  Drafted players stay listed (`drafted_round`/`drafted_by`) instead of
  disappearing; `rank` is value order across the whole class.
- **Roster capacity** — active-roster and taxi-squad slots filled/open.
  Deliberately does not model reserve/IR slots: how they interact with the
  active count isn't reliably derivable from the Sleeper API response alone,
  and an unclear rule is worse than not showing it.
- **Roster value analysis** — full roster sorted lowest-`adj_value` first.
  Doesn't treat "low value" as "drop" outright: age is weighed in, so a
  low-value *young* player is flagged as rebuild upside to hold, while
  low-value *aging* is a real drop candidate — matching this team's stated
  rebuild strategy rather than a generic cutoff.
- **Bye-week conflicts** and **weekly gaps** — the former flags specific
  players sharing a bye at a position; the latter checks, per week, whether
  the roster can actually fill its *dedicated* QB/RB/WR/TE slots (not
  FLEX/SUPER_FLEX — stated explicitly as a simplification, not modeled).
- **Handcuffs** — NFL depth-chart-derived RB backup pairing (latest snapshot
  of `nfl_data_py`'s depth-chart feed, which turned out to be a time series
  of scrapes rather than a single current view — confirmed by direct
  inspection before relying on it). Flags whether the user already owns a
  starter's handcuff, and flags available rookies who'd handcuff the user's
  own starters.
- **Lineup** — the `assign_starters` breakdown exposed directly as its own
  view (current-value snapshot; not week- or injury-aware yet — a planned
  refinement, not built here).
- **Draft plan** — every pick the user owns this draft, one table. Rounds
  already played show the *real* pick Sleeper recorded (retroactively scored
  the same marginal-value way), not a stale recommendation — refreshing
  after a round never hides what happened last round or breaks the table.
  Upcoming rounds are simulated assuming **no other team's picks happen in
  between** — "if these were your only remaining picks, back to back, on the
  board right now." This can't account for the other ~11 teams' behavior, so
  it's recomputed fresh on every refresh and stays realistic as the real
  draft actually progresses. Up to 2 backup alternates are shown per
  upcoming round, each checked for whether picking it instead would open a
  weekly gap the primary pick doesn't (`alternate_gap_note`) — a plain
  string, deliberately, so more note types (e.g. injury history, if that
  data ever becomes available) can be added later without a redesign.
  Finally compares the plan's resulting roster's weekly gaps against the
  current roster's, flagging any week the full plan would newly break.

## Performance

Marginal-value ranking evaluates every available candidate per round across
18 simulated weeks each — roughly 20,000 `assign_starters` calls for a
5-round plan over ~227 candidates. `fc_value_by_sleeper_id()` builds the
FantasyCalc value lookup **once** per refresh and is threaded through every
function that needs it, instead of each one rebuilding it from the raw
~475-entry list on every call. Full `gather_state()` completes in ~3.5-4s,
timed directly — acceptable for a manual Refresh click, not for anything
tighter.

## Known limitations (by design, not oversight)

- No real per-player scoring recompute — the QB/TE correction is a targeted
  fix for the two biggest gaps, not a full model.
- Draft-plan simulation assumes no other team picks in between the user's
  own picks — genuinely can't be predicted.
- `roster_weekly_gaps` doesn't model FLEX/SUPER_FLEX, only dedicated slots.
- `roster_capacity` doesn't model reserve/IR slots.
- Lineup and handcuff logic have no injury-status awareness.
- Handcuffs are RB-only — the standard fantasy usage of the term.
