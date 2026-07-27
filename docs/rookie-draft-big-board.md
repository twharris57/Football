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
| `nfl_data_py` | NFL schedules (bye weeks), depth charts (handcuffs), and weekly/play-by-play stats (per-player real-scoring recompute, see `player_scoring.py`) — all public, free, and already a project dependency |

## Valuation: market baseline + a per-player correction, not a full model

FantasyCalc's API only exposes three knobs: superflex (`numQbs`), league size,
and PPR. It has no parameter for the rest of this league's non-standard
scoring — 6-point passing touchdowns, a non-standard passing-yardage rate, a
-3 (not the usual -2) interception penalty plus an *additional* -6 if that
interception is returned for a touchdown (`pass_int_td` — found via a
one-time scoring_settings audit, not caught by the original per-INT-only
correction), a TE reception premium, and first-down/long-play bonuses.

`player_scoring.py` corrects for all of it, per player, wherever real NFL
history exists: for anyone with a qualifying season in the last 3 years (same
"startable volume" spirit as the original QB/TE-only version below, extended
to RB/WR), it recomputes that player's own points under this league's exact
`scoring_settings` (using raw weekly stats, plus play-by-play data for the
yardage-gated long-play bonuses and the pick-six penalty, neither of which
weekly aggregates capture) and divides by their points under FantasyCalc's
assumed baseline model (an explicit, documented assumption — FantasyCalc
doesn't publish its own formula). Below
the qualifying bar, or for rookies with no NFL history at all, a position
average computed from that same pooled sample is used instead —
`POSITION_VALUE_MULTIPLIER` is now a last-resort constant, used only if this
whole enrichment fails for a refresh. Results are cached to disk (no
TTL — the underlying seasons are historical and don't change on a clock) and
recomputed only on a "force full refresh."

`_sane_ratio()` guards every computed ratio before it's used: a
near-zero/negative pooled `baseline_points` (`<= 1.0`, which would blow the
ratio up or invert its sign) or a result outside `MULTIPLIER_BOUNDS`
(`[0.5, 2.0]`) falls back to the position average instead, then to
`POSITION_VALUE_MULTIPLIER` if even that's unavailable — real observed
ratios across a 332-player sample land in `[1.08, 1.61]`, comfortably
inside the bound, so this is a defensive floor against a bad data pull, not
a normal code path. Covered by `tests/test_player_scoring.py`
(`TestSaneRatio`).

The original version of this correction (superseded, kept here for context on
how the project arrived at the current approach) used one flat multiplier per
position instead of a per-player one, and covered only the two largest gaps
(6pt passing TDs, TE premium) — pulled from a single season's stats
(`POSITION_VALUE_MULTIPLIER`'s `QB: 1.164`/`TE: 1.204`, from 2024 alone, then
`1.175`/`1.202` once pooled across 3 seasons), applied via a now-removed
`adjusted_value()` function. The raw FantasyCalc `value` is still kept
alongside the corrected `adj_value` everywhere for comparison, not
overwritten.

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
bench piece. Taxi/IR players are excluded from ever winning that
`assign_starters` call (Sleeper doesn't allow starting them) but stay in
the drop-candidate pool itself — a low-value taxi stash can and should
still lose out to a high-value new candidate, confirmed directly with a
synthetic repro. A drop is only forced at all when the roster is at total
capacity (`roster_total_capacity()`: active roster slots + taxi slots +
reserve/IR slots — the last of these was a real bug, found and fixed
2026-07-26: it originally omitted `reserve_slots` from the ceiling
entirely, so an existing IR occupant's headcount silently eroded
active/taxi capacity instead of its own bucket, misreading a genuinely
open taxi slot as "no room" and recommending a nonsensical cut of a real
starter) — a pre-draft review caught the original version of this bug:
`rank_by_marginal_value()` used to call `recommend_drop()` unconditionally
for every candidate, even with open roster/taxi room, which understated
marginal value for any pick that didn't actually need to cost a roster
spot. Covered by `tests/test_dynasty_core.py` (`TestCapacityAwareDrop`) as
a regression guard. Rookies are assumed taxi-eligible for this check (true for every
candidate in this draft); a general accrued-experience eligibility model
is deferred (see `.claude/PROJECT_PLAN.md`).

## Features

- **Picks until your turn** (`picks_until_turn()`) — how many picks by
  anyone happen before the user's next one; `0` means it's their turn now,
  `None` means no picks remain. Small, but meaningfully improves usability
  on a phone mid-draft.
- **Rookie big board** — the whole rookie class, not just what's left.
  Drafted players stay listed (`drafted_round`/`drafted_by`) instead of
  disappearing; `rank` is value order across the whole class.
- **Roster capacity** — active-roster, taxi-squad, and IR/reserve slots
  filled/open. IR/reserve turned out to be reliably derivable after all
  (`roster["reserve"]`, same plain player_id list shape as `roster["taxi"]`
  — confirmed directly against rosters elsewhere in the league that
  currently have IR players) — a prior version of this doc said otherwise.
  `roster_total_capacity()` (used to decide whether a drafted rookie forces
  a drop) still deliberately excludes reserve/IR: it's a separate allotment
  for an already-rostered, injured player, not room for a new one.
- **Roster value analysis** — full roster sorted lowest-`adj_value` first.
  Doesn't treat "low value" as "drop" outright: age is weighed in, so a
  low-value *young* player is flagged as rebuild upside to hold, while
  low-value *aging* is a real drop candidate — matching this team's stated
  rebuild strategy rather than a generic cutoff. The aging cutoff itself is
  position-aware (`LOW_VALUE_AGING_AGE`: RB 27 / WR 29 / TE 30 / QB 33, with
  a 29 default) rather than one flat age for every position — dynasty RBs
  decline earlier than QBs/TEs, who often start productively much later.
  A `status` column gives a compact icon summary of each player's situation
  — 🆕 rookie (no NFL experience yet, `years_exp` falsy), 🏥 injury, 🌱 taxi
  squad, 🩹 IR/reserve — icons rather than words to stay space-efficient in
  a table column; a player can show more than one at once (e.g. a rookie
  stashed on taxi). `player_status_details()` pairs each icon with its
  specific description (e.g. the real `injury_status` word, expanding a
  cryptic Sleeper abbreviation like `PUP` where needed via
  `INJURY_STATUS_DESCRIPTIONS`) — `player_status_flags()` is the icon-only
  string built from it, for plain-text display (the CLI). In Streamlit,
  this table renders as plain HTML (`show_status_table()`) instead of
  `st.dataframe`, specifically so each status icon gets a real per-cell
  hover tooltip with its description — `st.dataframe`'s `column_config`
  only supports a tooltip on the column header, not per cell.
- **Bye-week impact** and **weekly gaps** — the former (`roster_bye_conflicts`)
  shows every week with an active-roster player on bye: who's out, who fills
  in, and the resulting delta to optimal starting-lineup value versus a
  full-strength week — replacing a plain "2+ players share a bye" headcount,
  which couldn't distinguish a well-covered bye from a costly one. Reuses
  the same per-week `assign_starters` machinery as
  `season_average_starter_value`, restricted to active-roster players only
  (taxi/reserve excluded — they can't actually be started to cover a bye).
  `starters_out` (players actually bumped from the lineup) is kept separate
  from `bench_out` (bye'd players who weren't starting anyway, so they don't
  move `lineup_delta`) — a bench player's bye shouldn't read as a problem
  just because it also happened. In Streamlit, each week is its own
  collapsible section: collapsed shows only `starters_out`/`fillers`/delta,
  expanded adds `bench_out` and a plain-language breakdown. An ✅/📅 cue
  distinguishes a week that's already happened from one still ahead, using
  `league["settings"]["leg"]` (Sleeper's current-week counter). A week
  already past still shows this same roster-based projection, not a real
  result — there's no live in-week stats feed yet, and the UI says so
  explicitly rather than implying otherwise.
  The latter (`roster_weekly_gaps`) checks, per week, whether the roster can
  actually fill its *dedicated* QB/RB/WR/TE slots (not FLEX/SUPER_FLEX —
  stated explicitly as a simplification, not modeled) — a depth signal, not
  a value one; the two are complementary.
- **Handcuffs** — NFL depth-chart-derived RB backup pairing (latest snapshot
  of `nfl_data_py`'s depth-chart feed, which turned out to be a time series
  of scrapes rather than a single current view — confirmed by direct
  inspection before relying on it). Flags whether the user already owns a
  starter's handcuff, and flags available rookies who'd handcuff the user's
  own starters. **Rookies rarely show up here pre-season** — verified
  directly: of a 227-player rookie class, only 11 had a `gsis_id`/`sleeper_id`
  mapping in `nfl.import_ids()` at all, and only 2 of those appeared anywhere
  in the real RB depth chart. Not a join bug — `nfl_data_py`'s ID crosswalk
  itself hasn't caught up with the incoming class yet; expect `handcuff_to`
  to fill in gradually later in the year, not all at once.
- **Lineup** — the `assign_starters` breakdown exposed directly as its own
  view (current-value snapshot; not week- or injury-aware yet — a planned
  refinement, not built here), with separate Starters/Bench/Taxi/IR sections
  (`lineup_breakdown()`) — taxi and IR players are both in `roster["players"]`
  alongside the real bench, so they're split out by cross-referencing
  `roster["taxi"]`/`roster["reserve"]` rather than left lumped into "bench".
- **Draft plan** — every pick the user owns this draft. Rounds already
  played show the *real* pick Sleeper recorded (retroactively scored the
  same marginal-value way), not a stale recommendation — refreshing after a
  round never hides what happened last round or breaks anything. Upcoming
  rounds are simulated assuming **no other team's picks happen in
  between** — "if these were your only remaining picks, back to back, on the
  board right now." This can't account for the other ~11 teams' behavior, so
  it's recomputed fresh on every refresh and stays realistic as the real
  draft actually progresses. Up to 2 backup alternates are computed per
  upcoming round, checked for whether picking one instead would open a
  weekly gap the primary pick doesn't (`alternate_gap_note`) — a plain
  string, deliberately, so more note types (e.g. injury history, if that
  data ever becomes available) can be added later without a redesign.
  Finally compares the plan's resulting roster's weekly gaps against the
  current roster's, flagging any week the full plan would newly break.
  In Streamlit, each pick is its own collapsible section rather than one
  flat table — collapsed shows the pick, drop, and marginal value with a
  ✅/🔜 cue for completed vs. upcoming and a ⚠️ if the suggested drop is a
  current starter; expanded holds the full reasoning and that pick's own
  backup options (folded in here rather than a separate table, since each
  round never had more than 2 alternates anyway).

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

- Draft-plan simulation assumes no other team picks in between the user's
  own picks — genuinely can't be predicted.
- `roster_weekly_gaps` doesn't model FLEX/SUPER_FLEX, only dedicated slots.
- Lineup and handcuff logic have no injury-status awareness.
- Handcuffs are RB-only — the standard fantasy usage of the term.

## Known gaps (oversights, tracked in `.claude/PROJECT_PLAN.md`)

- `lineup_breakdown`, `season_average_starter_value`, and
  `rank_by_marginal_value` all feed `assign_starters` the entire
  `roster["players"]` list, including taxi and IR/reserve players — none of
  whom Sleeper actually allows into the starting lineup. Found while
  building the bye-week-impact feature above, which correctly excludes
  them; the older functions don't yet. Hasn't visibly surfaced (today's
  taxi/IR values happen to be lower than the real bench), but is a latent
  correctness gap, not a style inconsistency.

## Static assumptions — revisit if the league's rules ever change

Most league-specific numbers are pulled live from Sleeper every refresh —
`roster_positions`, `taxi_slots`, `scoring_settings`, `num_teams`, PPR,
superflex count, draft rounds/teams — deliberately, so a commissioner
settings change doesn't require a code change. A few things aren't pulled
live, either because Sleeper doesn't expose them cleanly or because they're
judgment calls rather than league rules. Listed here so changing any of them
is a deliberate decision, not a silent bug:

| Assumption | Where | What breaks if it's ever wrong | If the league changes this |
|---|---|---|---|
| Draft type is `"linear"` (same slot order every round) | `compute_pick_ownership` | Guarded — raises `ValueError` instead of silently computing wrong pick ownership (a snake draft reverses slot order on even rounds; not implemented, since it's never been needed) | Add snake-order support if the league ever switches |
| Roster only uses QB/RB/WR/TE/FLEX/SUPER_FLEX slot types | `assign_starters`, `roster_weekly_gaps` | Any other Sleeper slot type (`WRRB_FLEX`, `REC_FLEX`, K, DEF, IDP) would be silently ignored — not assigned, not counted, no error | Extend `FLEX_ELIGIBLE_POSITIONS`/`SUPERFLEX_ELIGIBLE_POSITIONS` and the slot-processing loop for the new type |
| `POSITION_VALUE_MULTIPLIER` (`QB: 1.175`, `TE: 1.202`) | `dynasty_core.py` | Last-resort fallback only (see step B, above) — stale numbers only matter if the whole `player_scoring.py` enrichment fails for a refresh | Re-run `scripts/derive_position_multipliers.py`; not urgent since it's a fallback, not the primary path |
| `player_scoring.BASELINE_SCORING` (FantasyCalc's assumed scoring model) | `player_scoring.py` | The entire per-player correction ratio is only as good as this guess — FantasyCalc doesn't publish its real formula, so it can't be verified directly | No way to verify against FantasyCalc directly; revisit only if FantasyCalc publishes methodology notes, or the correction looks systematically off |
| `player_scoring.QUALIFYING_VOLUME` (QB ≥200 att / RB ≥100 carries / WR ≥50 targets / TE ≥30 targets) | `player_scoring.py` | Not derived from any league rule — a manual judgment call for "enough volume to trust a personalized ratio" | Revisit only if personalized ratios look noisy for borderline players |
| `YOUNG_CORE_MAX_YOE` / `YOUNG_CORE_NEED_THRESHOLD` / `LOW_VALUE_YOUNG_AGE` / `LOW_VALUE_AGING_AGE` | `dynasty_core.py` | Subjective heuristics behind the rebuild-strategy "need"/"low value" flags, not derived from any league setting | Adjust by feel as the roster ages into (or out of) the rebuild window |
| `max_keepers: 1` in the league's Sleeper settings | Not modeled anywhere | Appears vestigial for a dynasty-type league (Sleeper `type: 2`) — the whole roster carries over every year, not a limited keeper count, so this setting doesn't seem to apply | Revisit only if Sleeper's dynasty/keeper interaction is ever observed to actually matter |
