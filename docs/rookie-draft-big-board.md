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
doesn't publish its own formula). Below the qualifying bar, a rookie with a
matched combine profile gets that position's play-style-bucket average (see
below); everyone else below the bar falls back to the flat position
average computed from that same pooled sample — `POSITION_VALUE_MULTIPLIER`
is now a last-resort constant, used only if this whole enrichment fails for
a refresh. Results are cached to disk (no TTL — the underlying seasons are
historical and don't change on a clock) and recomputed only on a "force
full refresh."

`_sane_ratio()` guards every computed ratio before it's used: a
near-zero/negative pooled `baseline_points` (`<= 1.0`, which would blow the
ratio up or invert its sign) or a result outside `MULTIPLIER_BOUNDS`
(`[0.5, 2.0]`) falls back further up the chain instead — real observed
ratios across a 332-player sample land in `[1.08, 1.61]`, comfortably
inside the bound, so this is a defensive floor against a bad data pull, not
a normal code path. Covered by `tests/test_player_scoring.py`
(`TestSaneRatio`).

**Modeling assumption, stated explicitly (2026-07-31 valuation review):**
`adj_value = value * multiplier` applies a points-derived ratio
multiplicatively to FantasyCalc's market value, which assumes dynasty value
scales linearly with points under the counterfactual scoring rule. That's a
reasonable first-order approximation — it's what most scoring-format
converters do — but real dynasty value is plausibly convex near the top of
a position (scarcity premium) and flatter near replacement, so a flat ratio
could over-correct elite players and under-correct replacement-level ones
at the same position. Not something this project can verify directly any
more than `BASELINE_SCORING` itself can (see below); revisit the modeling
here specifically if `adj_value` ever looks systematically off at one end
of a position's range rather than uniformly. Tracked as part of the
post-draft valuation retrospective in `.claude/PROJECT_PLAN.md`.

### Rookie play-style buckets (valuation step A)

A flat position average doesn't distinguish a mobile QB from a pocket
passer, or a receiving TE from an in-line blocker — plausibly relevant
here, since this league's scoring gap (6pt passing TDs, TE reception
premium, long-play bonuses) rewards those profiles differently.
`_derive_rookie_buckets()` splits each position into two play-style buckets
using NFL Scouting Combine testing data (`import_combine_data`), a real
per-rookie athletic signal available without college stats:

- **QB** — 40-yd dash: faster → `mobile`, slower → `pocket`. Rushing
  production isn't boosted by the 6pt passing-TD rule the way pocket
  passing volume is.
- **RB** — weight: lighter → `receiving_back`, heavier → `early_down`.
  Reception/first-down bonuses matter more to receiving-back usage.
- **WR** — 40-yd dash: faster → `deep_threat`, slower → `possession`. The
  `40p`/`50p` long-play bonuses reward exactly the deep-threat profile.
- **TE** — a weight+40 composite (z-scored, summed): lower → `receiving`,
  higher → `in_line`. Receiving TEs earn more of the TE reception premium
  than blocking-heavy TEs who see fewer targets.

Each position's split point is the median of that metric among
combine-matched **historical** qualifying players (via a `pfr_id` →
`gsis_id` crosswalk from `import_ids()`) — real observed samples run
77-203 combine-matched player-seasons per position (2022-2024 pool, see
`QUALIFYING_VOLUME`), comfortably above `MIN_BUCKET_PLAYER_SEASONS` (10)
per bucket. Each bucket's ratio is pooled the same way `position_average`
is (`_sane_ratio` on the bucket's summed real/baseline points). This
year's incoming rookies are then classified into a bucket by the same
threshold, via their own combine number (`pfr_id` → `sleeper_id`, same
crosswalk) — deliberately rescoped to rookies only, via a *separate*
`import_combine_data` call for just the current season's class, not a
general veteran-inclusive bucket system (a veteran with real NFL history
already gets a more accurate per-player ratio directly, so bucketing them
too would only ever be thrown away).

**Real coverage is partial, by design, not a bug**: a rookie needs both a
combine invite and a `sleeper_id` crosswalk match to land in a bucket —
confirmed directly against the actual 2026 class, roughly half of
combine-matched rookies crosswalk to a `sleeper_id`, and QBs skip the
40-yard dash more often than other positions (68% completeness across
2015-2026 in a direct check, lower still in some single-year classes).
Every rookie who doesn't get a bucket match simply falls back to the flat
`position_average`, same as before this feature existed — never a worse
outcome, only sometimes a less specific one. `scripts/derive_position_multipliers.py`
prints the resolved rookie bucket ratios for direct inspection.

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
  a drop) counts only *occupied* reserve/IR slots toward the ceiling
  (`reserve_filled`, the roster's actual current headcount there), not the
  league's full `reserve_slots` setting — a drafted rookie can never
  actually be assigned to reserve (that requires a real injury
  designation, unlike taxi), so an empty IR slot isn't room for one. An
  earlier version added the full `reserve_slots` setting unconditionally,
  which let a league with unused reserve slots silently skip a forced drop
  on the first few picks of a draft plan (found via a live-draft bug
  report, fixed 2026-07-27). The taxi squad itself is unusually generous
  for a dynasty league — 5 slots, 3 years — more room to stash rookies
  without a roster crunch.
- **Roster needs: two different signals, not one** (valuation step toward
  post-draft trade tooling — see `.claude/PROJECT_PLAN.md`). The original
  `need` flag (`roster_needs_summary`) is a rebuild-*timeline* question:
  fewer than `YOUNG_CORE_NEED_THRESHOLD` players at a position with
  `<= YOUNG_CORE_MAX_YOE` years of experience — "are we still accumulating
  enough young talent here." It says nothing about whether the position's
  *actual value* is any good, and a same-roster "share of total value"
  metric would have a real flaw: one elite player at any position inflates
  its own share and makes every other position look artificially weak by
  comparison, even if they're all fine in absolute terms. `weak` (new
  `vor` column, `positional_strength_summary`) answers a trade-*strategy*
  question instead, against an external baseline: `position_replacement_levels()`
  computes each position's league-wide replacement level — the Nth-best
  rostered player at that position across every team's roster, where N =
  `_position_starter_demand()` (this league's dedicated starting slots at
  that position, times the number of teams) — a standard value-based-drafting
  concept. A team's own top N players at a position (same `_position_starter_demand()`
  count — deep bench doesn't count, it never plays) sum to `starter_value`;
  `vor` is `starter_value - (replacement_level * N)`, and `weak` is `vor <= 0`
  — this position's actual starters aren't even worth what's freely
  available elsewhere in the league. `roster_needs_summary` and
  `positional_strength_summary` are joined on position into one
  `roster_needs` table (`team_roster_analysis`) rather than kept as two
  separate ones, since they're both "per position" views a user would want
  side by side. Works for any team via the Roster tab's team selector,
  not just the user's own — the same `replacement_level` baseline (computed
  once per refresh across every roster) applies regardless of whose roster
  is being viewed.

  **SUPER_FLEX-aware QB demand (fixed 2026-08-01, found in a same-day
  valuation review):** the first version of `_position_starter_demand()`
  (then inlined directly) counted only dedicated slots for every position,
  which silently reverted QB to single-QB-league demand in this confirmed
  superflex league — `roster_positions` has one dedicated `QB` slot and one
  `SUPER_FLEX` slot, and the market-value layer already treats those as two
  startable QBs (`num_qbs = count("QB") + count("SUPER_FLEX")`, passed to
  `fantasycalc.get_dynasty_values()`), so the VOR overlay's dedicated-only
  count was inconsistent with the market data it's built on top of.
  `_position_starter_demand()` now adds `roster_positions.count("SUPER_FLEX")`
  to QB's demand specifically (matching that same `num_qbs` pattern, not a
  new assumption), which roughly doubles the QB replacement-level rank (12
  → 24 in this league) and pulls the cutoff to a meaningfully lower, more
  realistic value. Verified directly against live data: the league-wide
  rank-24 QB is a real, independently-confirmed player (not a
  self-referential artifact) — QB `vor` for the user's own roster went from
  a coincidental ≈0 to a genuine positive surplus once the deeper, correct
  cutoff was used. FLEX demand for RB/WR/TE is **not** covered by this fix
  — unlike SUPER_FLEX's near-total lean toward a 2nd QB in this format,
  FLEX splits demand across three positions with no similarly clean
  allocation; doing it properly needs a joint model of relative positional
  depth, not a simple per-position count. Still the same "ignores FLEX"
  simplification `roster_weekly_gaps` already makes deliberately — a known,
  tracked gap for those three positions, not silently expanded scope here.
  See `.claude/conventions/valuation_principles.md` for the durable rule
  this fix follows ("superflex inflates QB value — model it as such,
  everywhere").
- **Team timeline / power-timeline read** (`team_power_timeline_scores()`)
  — every team's rebuild-vs-contend read, not just the user's own, and a
  *continuous* score rather than a fixed two- or three-point label from the
  start (the plan's own "consider a continuous score, not just discrete
  phase labels" note) — display buckets are thresholds on the score, not a
  separate computation. Combines three signals, each z-scored across the
  whole league (population std, `ddof=0`, deliberately — every team here
  genuinely *is* the whole population, not a sample, and it sidesteps the
  single-team-league `NaN` a sample std would produce) so none can dominate
  by raw scale alone, then averaged with equal weight — a starting judgment
  call to revisit by feel (see `valuation_principles.md`), not a derived
  constant:
  - **Roster strength** — `positional_strength_summary()`'s `vor` summed
    across positions, reusing the SUPER_FLEX-aware replacement-level work
    directly rather than a second strength model.
  - **Timeline direction** — `_weighted_average_age()`: value-weighted
    average roster age, not a flat one. An old bench piece shouldn't count
    the same as an old franchise cornerstone toward "how win-now is this
    roster" — weighting by `adj_value` fixes that.
  - **Actual record** — real `wins / (wins + losses + ties)` from Sleeper's
    standings, not just projected strength: a thin roster on a hot streak
    and a stacked roster off to a bad start are both real signals a
    roster-composition-only read would miss entirely. Defaults to a neutral
    `0.5` with zero games played (true pre-season/pre-draft, confirmed
    directly) — every team ties at that same neutral value then, so the
    term contributes zero variance and the score reduces to strength +
    timeline alone until real results exist. Not a special case coded
    around; an emergent property of z-scoring a constant.

  Recomputed fresh every refresh from already-pulled data (no new API
  calls) rather than cached, so it reacts to injuries, trades, and real
  results automatically instead of ever going stale — directly addresses
  the plan's concern that a label computed once and left alone would go
  stale exactly when a real event (an injury, a team realizing they're one
  piece away) should have moved it. Computed once for the whole league in
  `gather_state` (every team's row is needed together for the z-scoring
  itself), unlike `team_roster_analysis`'s per-team on-demand pattern — a
  UI just looks up the selected team's row. Verified directly against live
  data: the user's own team (a confirmed year-one rebuild, see `CLAUDE.md`)
  reads as `rebuilding` with the lowest score in the league; the roster
  with the league's highest-value QB reads as `contending` — both
  consistent with what's independently known about the real league.

  `rank` (1 = strongest `power_score` in the league) and `games_played`
  are also exposed, both display-only derivatives rather than separate
  computations — a raw z-score isn't something a user should have to
  interpret cold, so the UI/CLI lead with "3 of 12" instead, with the raw
  score available as a tooltip/aside for anyone who wants it.
  `games_played == 0` is the signal a UI needs to show "no games played
  yet" instead of a misleading flat 50% win rate before the season starts
  — without it, every team's win% looks identical and real, not like the
  neutral placeholder it actually is.

  `power_score` blends two conceptually different axes — "how good is
  this roster right now" (strength + record) and "which way is it
  pointed" (timeline) — which averages away the distinction between a
  strong/young/ascending team and a weak/old/declining one landing on the
  same number. `quality_score` (strength + record, z-scored and averaged)
  and `timeline_score` (timeline, z-scored) are exposed separately for
  exactly that reason, so a downstream consumer that needs to tell those
  two cases apart (the planned trade-target/sell evaluator) can reason
  about them independently rather than re-deriving the same z-scores —
  see `.claude/PROJECT_PLAN.md`'s "Roster & trade tooling" for the
  assistant valuation review that caught this. `power_score`/`phase`
  stay as the at-a-glance UI read; this is additive.

  A **Glossary** (`GLOSSARY` dict + an `st.dialog` in `streamlit_app.py`,
  behind a "❓ Glossary" button next to the page title) defines VOR, power
  score, and adj. value in one reachable place — added after user feedback
  that VOR was previously only explained inside the Roster needs section's
  own "How this works" expander, easy to miss from anywhere else in the
  app.
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
- `position_replacement_levels()`/`positional_strength_summary()` set each
  position's replacement rank from *dedicated* slots only
  (`roster_positions.count(pos) * num_teams`) — the same FLEX/SUPER_FLEX
  simplification `roster_weekly_gaps` makes, listed above as a deliberate
  limitation. For QB specifically, in this confirmed superflex league, that
  simplification isn't neutral: true QB demand is closer to two startable
  QBs per team (this project's own market-value call already knows this —
  `num_qbs` is `count("QB") + count("SUPER_FLEX")`), so using only the
  dedicated count sets QB's replacement baseline too high and
  systematically understates QB's `vor`. Found via the 2026-07-31 valuation
  review; tracked as Roster & trade tooling item 1 in
  `.claude/PROJECT_PLAN.md`, since the upcoming power/timeline read and
  trade-targets tooling would otherwise inherit this bias. See
  `.claude/conventions/valuation_principles.md` for the general rule this
  is an instance of.

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
| `BASELINE_SCORING["rec"] = 1.0`, hardcoded independent of the real `ppr` sent to FantasyCalc | `player_scoring.py` | `get_dynasty_values()` already sends this league's real PPR to FantasyCalc, so its market value is calibrated to it — but `BASELINE_SCORING` assumes `1.0` regardless. Harmless while the league stays full PPR (`rec: 1.0`); if it's ever changed, the correction ratio would silently conflate the intended residual-scoring delta with an unintended PPR delta FantasyCalc's own call already priced in (see `.claude/PROJECT_PLAN.md`, Valuation & data accuracy item 2) | Thread the real `ppr` value into `BASELINE_SCORING["rec"]` instead of the literal `1.0` |
| `player_scoring.QUALIFYING_VOLUME` (QB ≥200 att / RB ≥100 carries / WR ≥50 targets / TE ≥30 targets) | `player_scoring.py` | Not derived from any league rule — a manual judgment call for "enough volume to trust a personalized ratio" | Revisit only if personalized ratios look noisy for borderline players |
| `YOUNG_CORE_MAX_YOE` / `YOUNG_CORE_NEED_THRESHOLD` / `LOW_VALUE_YOUNG_AGE` / `LOW_VALUE_AGING_AGE` | `dynasty_core.py` | Subjective heuristics behind the rebuild-strategy "need"/"low value" flags, not derived from any league setting | Adjust by feel as the roster ages into (or out of) the rebuild window |
| `max_keepers: 1` in the league's Sleeper settings | Not modeled anywhere | Appears vestigial for a dynasty-type league (Sleeper `type: 2`) — the whole roster carries over every year, not a limited keeper count, so this setting doesn't seem to apply | Revisit only if Sleeper's dynasty/keeper interaction is ever observed to actually matter |
