# Rookie Draft Big Board — Logic & Methodology

What `dynasty/dynasty_core/` computes: a full analysis of the user's Sleeper dynasty
league (id `1324888291937386496`, "Dynasty Degenerates") ahead of and during
the rookie draft — who to pick, who to drop, and what that does to the roster
across a season. Consumed by `dynasty/streamlit_app.py` (web dashboard);
see `docs/dynasty-draft-web-app.md` for the presentation layer.

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
interception is returned for a touchdown (`pass_int_td`), a TE reception
premium, and first-down/long-play bonuses.

`player_scoring.py` corrects for all of it, per player, wherever real NFL
history exists: for anyone with any real volume in the last 3 seasons, it
recomputes that player's own points under this league's exact
`scoring_settings` (using raw weekly stats, plus play-by-play data for the
yardage-gated long-play bonuses and the pick-six penalty, neither of which
weekly aggregates capture) and divides by their points under FantasyCalc's
assumed baseline model (an explicit, documented assumption — FantasyCalc
doesn't publish its own formula). That own-ratio is then shrunk toward the
position average by volume (`_shrunk_ratio()`, weight `volume / (volume +
k)` where `k = QUALIFYING_VOLUME[position] * LOOKBACK_SEASONS` — same shape
as the power/timeline read's `_shrunk_win_pct()`, with the single-season
qualifying bar scaled up to the multi-season window `volume` is actually
summed over): a player whose lookback-window volume matches "meaningful
starter" *every* season in the window gets their own signal at half
weight, well below it leans mostly on the position average, well above it
mostly trusts its own number, with no hard cutoff between the two. A
player with no real NFL history at all (a rookie) gets a
matched combine profile's play-style-bucket average instead (see below);
everyone else with neither falls back to the flat position average —
`POSITION_VALUE_MULTIPLIER` is a last-resort constant, used only if this
whole enrichment fails for a refresh. Results are cached to disk (no TTL —
the underlying seasons are historical and don't change on a clock) and
recomputed only on a "force full refresh."

`_sane_ratio()` guards every computed ratio (a player's own, and the
position average it's shrunk toward) before it's used: a near-zero/negative
pooled `baseline_points` or a result outside `MULTIPLIER_BOUNDS`
(`[0.5, 2.0]`) falls back further up the chain instead of being used
directly — real observed ratios land in `[1.08, 1.61]`, so this is a
defensive floor against a bad data pull, not a normal code path. A player
whose own ratio fails this check falls back to the position average
unshrunk (not blended with an untrustworthy number); if the position
average itself fails it, that position's `per_player` entries are skipped
entirely for the refresh, same as an empty qualifying pool. Covered by
`tests/test_player_scoring.py` (`TestSaneRatio`, `TestShrunkRatio`).

**The correction never lowers value for RB/WR/TE** — every scoring-rule
difference this league adds for those positions is strictly additive, so
`ratio ≥ 1` is structurally guaranteed, not just observed. QB is the one
position with a real downward term (INT/pick-six penalties), so
`adj_value < value` is theoretically possible there, but hasn't happened
in the real data (lowest observed QB ratio: 1.23) — the TD/yardage-rate
lift dwarfs the penalty for any real-volume starter.

Because there's no renormalization step, this also isn't a zero-sum
reallocation — the correction doesn't shift value *from* one position *to*
another. It inflates every position's `adj_value`, just by different
amounts (position-average ratios: QB ~1.40, TE ~1.32, RB ~1.17, WR ~1.15).
What actually shifts is *relative* standing — QB/TE's share of total value
rises while RB/WR's falls — not any player's absolute number moving down.

**Modeling assumption:** `adj_value = value * multiplier` applies a
points-derived ratio multiplicatively to FantasyCalc's market value, which
assumes dynasty value scales linearly with points under the counterfactual
scoring rule. That's a reasonable first-order approximation — it's what most
scoring-format converters do — but real dynasty value is plausibly convex
near the top of a position (scarcity premium) and flatter near replacement,
so a flat ratio could over-correct elite players and under-correct
replacement-level ones at the same position. Whether *market value itself*
responds linearly to a points change isn't directly verifiable (no ground
truth for that relationship, any more than `BASELINE_SCORING` itself has
one — see below), but the more tractable proxy question is checkable: does
the *scoring-correction ratio itself* (`real_points / baseline_points`, the
thing being multiplied) vary systematically with a player's value tier? If
it did, a flat ratio would compound the convexity risk; if it's essentially
flat across tiers, a uniform multiplier can't meaningfully distort relative
standing within a position regardless of how value itself truly responds to
points.

**Checked against real data, 2026-08-30** (3 lookback seasons, 2022-2024;
per-player-season ratios split into terciles by real-league points scored,
same qualifying-volume bars as `QUALIFYING_VOLUME`): the ratio is
essentially flat across tiers at every position — QB 1.39/1.38/1.41
(low/mid/high tier, n=108, corr with points = 0.20), RB 1.17/1.17/1.17
(n=141, corr = 0.03), WR 1.15/1.15/1.16 (n=263, corr = 0.25), TE
1.33/1.32/1.32 (n=135, corr = -0.10) — every position's tier-to-tier spread
is under 2%. This doesn't prove market value itself scales linearly with
points, but it substantially de-risks the concern in practice: the
multiplier applied is nearly the same number regardless of where a player
sits in their position's range, so the flat-ratio approximation isn't
compounding whatever non-linearity exists in the market's own response to
points. Revisit if `adj_value` ever looks systematically off at one end of
a position's range, or if this same per-tier ratio check, re-run on a later
season, stops looking flat — re-run it via
`scripts/check_scoring_correction_assumptions.py` rather than
reconstructing the query by hand.

An earlier version of this correction used one flat multiplier per position
covering only the two largest scoring gaps (6pt passing TDs, TE premium);
the per-player/per-bucket approach superseded it once qualifying-volume and
combine data were wired in. The raw FantasyCalc `value` is kept alongside
the corrected `adj_value` everywhere, not overwritten, so the correction's
effect stays visible.

### Rookie play-style buckets

A flat position average doesn't distinguish a mobile QB from a pocket
passer, or a receiving TE from an in-line blocker — relevant here, since
this league's scoring gap (6pt passing TDs, TE reception premium, long-play
bonuses) rewards those profiles differently. `_derive_rookie_buckets()`
splits each position into two play-style buckets using NFL Scouting Combine
testing data (`import_combine_data`), a per-rookie athletic signal available
without college stats:

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
combine-matched historical qualifying players (via a `pfr_id` → `gsis_id`
crosswalk from `import_ids()`), comfortably above `MIN_BUCKET_PLAYER_SEASONS`
(10) per bucket. Each bucket's ratio is pooled the same way
`position_average` is (`_sane_ratio` on the bucket's summed real/baseline
points). This year's incoming rookies are classified into a bucket by the
same threshold, via their own combine number (`pfr_id` → `sleeper_id`, same
crosswalk) — deliberately rescoped to rookies only, via a *separate*
`import_combine_data` call for just the current season's class, not a
general veteran-inclusive bucket system (a veteran with real NFL history
already gets a more accurate per-player ratio directly, so bucketing them
too would only ever be thrown away).

**Real coverage is partial, by design, not a bug**: a rookie needs both a
combine invite and a `sleeper_id` crosswalk match to land in a bucket —
roughly half of combine-matched rookies crosswalk to a `sleeper_id`, and
QBs skip the 40-yard dash more often than other positions. Every rookie who
doesn't get a bucket match simply falls back to the flat `position_average`
— never a worse outcome, only sometimes a less specific one.
`scripts/derive_position_multipliers.py` prints the resolved rookie bucket
ratios for direct inspection.

**Checked whether a continuous score (regression over the bucket metric)
would meaningfully improve on the binary median split, 2026-08-30**: no —
the bucket metric itself has weak-to-negligible correlation with the real
ratio at every position (QB +0.12, RB +0.18, WR -0.23, TE -0.00, on 77-203
combine-matched historical player-seasons), and a simple linear regression
on that same metric barely beats the current two-bucket-mean prediction
(0.0-2.1% lower MSE, worst position first: TE -0.0%, RB +0.0%, QB +0.1%,
WR +2.1%). The two-bucket split is already capturing nearly all the
explainable variance a continuous model could — the underlying combine
signal is just weak, not under-modeled by a binary split. A regression-
based continuous score (feature selection, real overfitting risk against
a sample this size) isn't worth the added complexity for a gain this
small. Not picked up; revisit only if a richer feature set becomes
available — college target share, yards per route run, and draft capital
are all more predictive of rookie fantasy outcomes than combine testing
alone, so a future college-stats pipeline is a more promising path to a
worthwhile continuous score than adding more combine-only features to
this one. The weak correlation found here is a property of 40-yd-dash/
weight alone as predictors, not necessarily of a continuous approach in
general. Re-run via `scripts/check_scoring_correction_assumptions.py`
(same script as the linearity check above) rather than reconstructing the
query by hand.

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
  argument, not just a heuristic. Taxi/IR players (`ineligible_ids`) never
  win a slot here, matching Sleeper's own rule that they can't be started.
- **`season_average_starter_value()`** runs that assignment separately for
  each of the 18 NFL weeks, excluding players on bye that week, and averages
  the total across the season. Every player misses exactly one week (their
  own bye), so this doesn't inherently favor or penalize anyone for having a
  bye at all — what it captures correctly is the *interaction*: a pickup
  whose bye lines up with an already-thin position contributes less across a
  season than the same value somewhere with real depth behind it. Weekly-gap
  *detection* is a separate, dedicated feature (`roster_weekly_gaps`) — this
  is about the season-long value comparison, not gap alerts.
- **`rank_by_marginal_value()`** ties it together: for each candidate,
  simulate adding them (and making the resulting recommended drop), and
  measure the season-average delta. This can reorder picks in a real,
  non-trivial way against a pure-value baseline — a lower-value player at a
  thinner position can beat a higher-value one who's a worse marginal fit
  for the roster at that point in the plan.

`recommend_drop()` feeds the drop side: lowest-value **bench** player,
preferred over starters (via the same `assign_starters` assignment) — a
marginal starter isn't recommended for cut over a similarly valued deep
bench piece. Taxi/IR players are excluded from ever winning that
`assign_starters` call but stay in the drop-candidate pool itself — a
low-value taxi stash can and should still lose out to a high-value new
candidate. A drop is only forced at all when the roster is at total
capacity (`roster_total_capacity()`: active roster slots + taxi slots +
reserve/IR slots). Covered by `tests/dynasty_core/test_marginal_value.py`
(`TestCapacityAwareDrop`). Rookies are assumed taxi-eligible for this check
(true for every candidate in this draft); a general accrued-experience
eligibility model is deferred (see `.claude/PROJECT_PLAN_DYNASTY.md`).

## Features

- **Picks until your turn** (`picks_until_turn()`) — how many picks by
  anyone happen before the user's next one; `0` means it's their turn now,
  `None` means no picks remain.
- **Rookie big board** — the whole rookie class, not just what's left.
  Drafted players stay listed (`drafted_round`/`drafted_by`) instead of
  disappearing; `rank` is value order across the whole class.
- **Roster capacity** — active-roster, taxi-squad, and IR/reserve slots
  filled/open. `roster_total_capacity()` (used to decide whether a drafted
  rookie forces a drop) counts only *occupied* reserve/IR slots toward the
  ceiling (`reserve_filled`), not the league's full `reserve_slots`
  setting — a drafted rookie can never actually be assigned to reserve
  (that requires a real injury designation, unlike taxi), so an empty IR
  slot isn't room for one. The taxi squad itself is unusually generous for
  a dynasty league — 5 slots, 3 years — more room to stash rookies without
  a roster crunch.
- **Roster needs: two different signals, not one.** The `need` flag
  (`roster_needs_summary`) is a rebuild-*timeline* question: fewer than
  `YOUNG_CORE_NEED_THRESHOLD` players at a position with
  `<= YOUNG_CORE_MAX_YOE` years of experience — "are we still accumulating
  enough young talent here." It says nothing about whether the position's
  *actual value* is any good. `weak` (`vor` column,
  `positional_strength_summary`) answers a trade-*strategy* question
  instead, against an external baseline: `position_replacement_levels()`
  computes each position's league-wide replacement level — the Nth-best
  rostered player at that position across every team's roster, where N =
  `_position_starter_demand()` (this league's dedicated starting slots at
  that position, times the number of teams) — a standard value-based-drafting
  concept. A team's own top N players at a position sum to `starter_value`;
  `vor` is `starter_value - (replacement_level * N)`, and `weak` is
  `vor <= 0` — this position's actual starters aren't even worth what's
  freely available elsewhere in the league. Deliberately a league-wide
  baseline rather than a same-roster "share of total value" metric: one
  elite player at any position would inflate its own share and make every
  other position look artificially weak by comparison, even if all fine in
  absolute terms. `roster_needs_summary` and `positional_strength_summary`
  are joined on position into one `roster_needs` table
  (`team_roster_analysis`). Works for any team via the Roster tab's team
  selector, not just the user's own — the same `replacement_level` baseline
  (computed once per refresh across every roster) applies regardless of
  whose roster is being viewed.

  `_position_starter_demand()` counts `SUPER_FLEX` slots toward QB demand
  (not FLEX toward RB/WR/TE — no similarly clean allocation exists there;
  same simplification `roster_weekly_gaps` makes). See
  `.claude/conventions/valuation_principles.md`'s "superflex inflates QB
  value" rule for why.

  **`need` itself is phase-aware**, not one fixed rule for all time: while
  a team's rebuild-vs-contend phase (see "Team timeline" below) is
  `"rebuilding"`, `need` keeps the young-core-timeline reading above.
  Otherwise (`treading_water` or `contending`), `need` switches to mean the
  same thing as `weak` instead — once a team isn't framing itself as a
  bottom-of-standings rebuild anymore, "need" is a roster-hole question,
  not a youth-accumulation one. `_need_from_phase()` (`roster_needs.py`) is
  the single switch both `team_roster_analysis()` (which already has both
  columns joined for its own display) and `phase_aware_need_positions()`
  (for a caller with no such table, e.g. the draft plan's hypothetical
  rosters) apply, so the two can't quietly disagree. The same binary
  phase read also gates `roster_value_analysis()`'s drop-candidate `note`:
  the "low value, young → hold" exception only fires while rebuilding.
  A third piece of this same idea — opportunistic free-agent flagging
  shifting by phase — is treated as already covered by the in-season
  Pickup Alerts feature (Summary tab), not a gap needing separate
  phase-conditional logic here.
- **Team timeline / power-timeline read** (`team_power_timeline_scores()`)
  — every team's rebuild-vs-contend read, not just the user's own, as a
  *continuous* score rather than a fixed two- or three-point label — display
  buckets (`phase`: rebuilding/treading_water/contending) are thresholds on
  the score, not a separate computation. Combines three signals, each
  z-scored across the whole league (population std, `ddof=0` — every team
  here genuinely *is* the whole population, not a sample, and it sidesteps
  the single-team-league `NaN` a sample std would produce), then averaged
  with equal weight — a starting judgment call to revisit by feel:
  - **Roster strength** — `positional_strength_summary()`'s `vor` summed
    across positions, reusing the SUPER_FLEX-aware replacement-level work
    directly rather than a second strength model.
  - **Timeline direction** — `_weighted_average_age()`: value-weighted
    average roster age, not a flat one, so an old bench piece doesn't count
    the same as an old franchise cornerstone toward "how win-now is this
    roster."
  - **Actual record** — two separate fields, deliberately not one: `win_pct`
    is the real `(wins + 0.5 * ties) / (wins + losses + ties)` from Sleeper's
    standings — a tie earns standard half-win credit rather than scoring
    identically to a loss — exactly what the "Win %" display prints;
    `win_pct_shrunk`
    is what actually feeds the z-scoring, blended toward a neutral `0.5`
    early in the season (`_shrunk_win_pct()`, weight `games_played /
    (games_played + WIN_PCT_SHRINKAGE_K)`) so a 1-0/0-1 start doesn't swing
    the score as hard as a settled record does. Splitting them prevents the
    exact failure mode a statistical correction like this invites — see
    `.claude/conventions/valuation_principles.md`'s "a field used as both an
    internal score input and a user-facing label needs two names" rule.
    Both default to a neutral `0.5` with zero games played, so every team
    ties at that same value and the term contributes zero variance until
    real results exist — an emergent property of z-scoring a constant, not
    a special case coded around. A thin roster on a hot streak and a
    stacked roster off to a bad start are both real signals a
    roster-composition-only read would miss.

  Recomputed fresh every refresh from already-pulled data (no new API
  calls) rather than cached, so it reacts to injuries, trades, and real
  results automatically instead of ever going stale. Computed once for the
  whole league in `gather_state` (every team's row is needed together for
  the z-scoring itself), unlike `team_roster_analysis`'s per-team on-demand
  pattern.

  `rank` (1 = strongest `power_score` in the league) and `games_played` are
  also exposed, both display-only derivatives — the UI leads with "3 of
  12" rather than a raw z-score, with the raw score available as a
  tooltip/aside. `games_played == 0` is the signal a UI needs to show "no
  games played yet" instead of a misleading flat 50% win rate before the
  season starts.

  `power_score` blends two conceptually different axes — "how good is this
  roster right now" (strength + record) and "which way is it pointed"
  (timeline) — which averages away the distinction between a
  strong/young/ascending team and a weak/old/declining one landing on the
  same number. `quality_score` (strength + record, z-scored and averaged)
  and `timeline_score` (timeline, z-scored) are exposed separately so a
  downstream consumer that needs to tell those two cases apart (trade
  targets & sells, below) can reason about them independently rather than
  re-deriving the same z-scores. `power_score`/`phase` stay as the
  at-a-glance UI read.

  A **Glossary** (`GLOSSARY` dict + an `st.dialog` in `tabs/components.py`,
  behind a "❓ Glossary" button next to the page title) defines VOR, power
  score, and adj. value in one reachable place.
- **Roster value analysis** — full roster sorted lowest-`adj_value` first.
  Doesn't treat "low value" as "drop" outright: age is weighed in, so a
  low-value *young* player is flagged as rebuild upside to hold, while
  low-value *aging* is a real drop candidate. The aging cutoff itself is
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
  string built from it. This table renders as plain HTML
  (`show_status_table()`) instead of
  `st.dataframe`, specifically so each status icon gets a real per-cell
  hover tooltip with its description — `st.dataframe`'s `column_config`
  only supports a tooltip on the column header, not per cell.
- **Trade targets & sells** — two composed views, not a new valuation model
  (see `.claude/conventions/valuation_principles.md`):
  - **`sellable_players()`** — a team's own bench depth worth shopping, not
    just cutting. A position qualifies if its own top starters (the same
    per-position starter count `positional_strength_summary` uses for
    `starter_value`) clear replacement level (`vor > 0` — real surplus, not
    just headcount); within a qualifying position, only the roster's depth
    *beyond* those starters — plus the roster's `FLEX` slot count reserved
    against every FLEX-eligible position, since it isn't knowable up front
    which position actually fills it — is a candidate. A candidate must
    also survive `gap_delta` against the roster with them removed — depth
    isn't real surplus if a bye week actually needs it. Rookies are
    excluded (`years_exp` falsy) — dynasty upside to hold, not surplus to
    sell. Deliberately excludes actual starters (selling one is a much
    bigger strategic call than "there's unused depth here," left for a
    human to judge directly against a specific offer). Works through the
    Roster tab's team selector, so it shows any team's sellable depth, not
    just the user's own.
  - **`pick_trade_values()`** — every remaining/near-future draft pick,
    valued and owner-tagged, league-wide (a pick's owner is already a
    column, so this isn't filtered by the team selector). Matches
    FantasyCalc's own pick-name string (e.g. `"2026 Pick 1.01"`,
    `"2027 1st"`) — the only stable join key FantasyCalc exposes for picks.
    This season's remaining picks get an exact slot value via Sleeper's
    real draft object (`compute_pick_ownership`). Next season's picks
    (`FUTURE_PICK_YEARS_AHEAD = 1`) use FantasyCalc's flat, non-tiered
    round value applied the same to every team — there's no real
    projected-standings input a year out to justify guessing an
    Early/Mid/Late tier per team. Seasons beyond that aren't included —
    Sleeper's `traded_picks` only ever has entries for picks actually
    traded, so there's no real signal for "these are all the picks that
    will ever exist" further out. Uses FantasyCalc's raw `value`, not the
    per-player `adj_value` — a pick has no real statistical production for
    that correction to apply to.

  Deliberately out of scope: selling an actual starter (not just depth),
  and trade-block monitoring (watching for a specific player another team
  is shopping) — both need a real strategic judgment call or a signal
  Sleeper doesn't expose, tracked in `.claude/PROJECT_PLAN_DYNASTY.md`.
- **Free agents** (`free_agent_board()`) — every non-rostered fantasy-relevant
  player on a real NFL team (`free_agent_pool()`; Sleeper has no dedicated
  free-agent endpoint, same generalized approach as `rookie_pool`), ranked
  by season-average marginal starting-lineup value against a roster —
  reusing `rank_by_marginal_value` exactly like the draft plan does, not a
  second valuation model. Each candidate carries its own best-drop
  suggestion, same as the draft plan's alternates. Works through the Roster
  tab's team selector, so it shows any team's free-agent board, not just
  the user's own. Excludes this year's not-yet-drafted rookies
  (`draft_eligible_rookie_ids`, reusing `gather_state`'s own undrafted-rookie
  pool for the draft plan itself) for as long as the startup draft still has
  picks remaining — an undrafted rookie mid-draft is a draft prospect, not a
  waiver-wire pickup, even though nothing about `rostered_player_ids` would
  otherwise catch that. Once the draft is complete, this exclusion is an
  empty set and any still-undrafted rookie becomes a real free agent again
  automatically, no special-casing needed. Two further deliberate v1
  simplifications, both tracked in `.claude/PROJECT_PLAN_DYNASTY.md`:
  - **Active-roster-only capacity** — passes `taxi_eligible=False` to
    `roster_total_capacity()`/`rank_by_marginal_value()` (a new parameter,
    default `True` so the rookie draft plan's own behavior is unaffected),
    since Sleeper's real accrued-experience taxi rule isn't verified here.
    A candidate is only ever suggested for an open active slot or via a
    drop, never assumed to fit an open taxi slot the way a rookie safely
    can. `taxi_eligible=False` still credits `taxi_filled` (the roster's
    actual current taxi headcount) toward the ceiling rather than zeroing
    taxi capacity outright — an existing taxi stash (the norm for this
    league's rebuild strategy) is already-spent capacity, not "no room,"
    the distinction a 2026-08-02 review found this simplification had
    collapsed.
  - **FAAB bid guidance** (`dynasty_core/waiver_bids.py`) — real
    comparable bid history, not an invented formula. Sleeper's
    `/league/{id}/transactions/{leg}` endpoint records every waiver
    transaction with the actual dollar amount bid
    (`settings.waiver_bid`), win or lose; `won_bid_sample()` keeps only
    `status == "complete"` ones (a `"failed"` bid never cleared the
    market, so it isn't a real clearing price) and resolves each winning
    player's position and *current* `adj_value` — not their value at the
    time of the bid, which isn't reconstructable without historical
    roster/value snapshots this project doesn't keep, a reasonable proxy
    for the short in-season windows this covers today: this gets
    materially less accurate the further back a lookback reaches, worth
    revisiting with a recency-aware sample if guidance ever extends to
    prior seasons.
    `nearest_comparable_bids()` finds up to `COMPARABLE_NEAREST_K` real
    bids nearest a candidate's value (same position preferred, broadened
    to every position only when the same-position sample is under
    `MIN_SAME_POSITION`) — **except QB, which never broadens**: this
    league is superflex, so a QB can draw a real bidding premium purely
    from 2-QB-startable scarcity that a same-value RB/WR/TE never faces,
    and mixing a thin QB sample into other positions' bids would present a
    range built from a different demand curve than the one a QB candidate
    is actually being bid into. A live check of this league's own
    transaction history (2026-08-29) found only 2 real QB winning bids to
    date — too few to confirm or rule out the premium empirically, so QB
    stays a small-sample "not enough data yet" via `MIN_COMPARABLE_SAMPLE`
    rather than a broadened, mismatched-demand-curve range; revisit once a
    real QB sample exists to check against. Filtered to rows within
    `max(COMPARABLE_MAX_DISTANCE_PCT * candidate_adj_value,
    COMPARABLE_MIN_ABSOLUTE_DISTANCE)` of the candidate's own value — a
    count floor alone (`MIN_COMPARABLE_SAMPLE`) doesn't catch a sparse or
    value-skewed sample where the *nearest available* rows are still a
    wildly different tier of player, so a distance floor gates that
    separately (`valuation_principles.md`'s "nearest-neighbor needs a
    distance floor" rule). `bid_guidance()` returns those bids directly,
    each alongside its own `adj_value` so the UI can show a human the real
    match quality rather than asking them to trust it, plus a low/median/
    high computed from that exact list — never a separate model — or
    `None` below `MIN_COMPARABLE_SAMPLE` *close* comparables, an honest
    "not enough data yet" rather than a number from too few or too
    mismatched points. Computed on demand for one selected free-agent
    candidate at a time (Roster tab), not for the whole board every
    refresh.
  - **Pickup alerts** (the Summary tab's in-season monitor,
    `pickup_snapshots.py`/`state.py`) shares this same "what would this
    replace, and what's the impact" phrasing rather than a second one — a
    real team/depth-chart/status change surfaces alongside the exact
    `marginal_value`/`drop_name`/`drop_is_starter` fields `free_agent_board`
    rows already carry (same `rank_by_marginal_value()` call, just applied
    to the changed-player subset instead of the whole pool), formatted
    through the same shared `_impact_and_drop_note()` helper in
    `summary.py` so the two surfaces can't drift apart on how they describe
    the same signal.
- **Trade evaluator** (`evaluate_trade()`) — evaluates an arbitrary
  proposed trade (any number of players and/or picks on either side)
  between two selected teams, shown for both sides rather than a single
  fairness verdict. Reframed from an originally-scoped "watch the trade
  block" idea once real trade offers turned out to be two-sided and often
  multi-asset, not a single flagged player. Two independent reads, not
  blended into one number:
  - **Lineup value** — `season_average_starter_value()` before vs. after
    the trade (current roster minus outgoing players plus incoming
    players), the exact same machinery `rank_by_marginal_value` builds on,
    generalized to arbitrary multi-player in/out rather than one candidate
    at a time. A trade can be lineup-critical (fills a real hole) even
    when it's not the better deal by raw value, or vice versa.
  - **Asset value** — `adj_value` (players) plus pick `value`
    (`pick_trade_values`, resolved by the caller) summed on each side —
    the market-value "who gave up more" read, computed independently of
    the lineup read.
  - Evaluating "the other side" of the identical trade is the same
    function called again with the partner's own roster and the two asset
    lists swapped — not a second implementation.
  - `taxi_eligible=False` for the capacity check, same reasoning and same
    `taxi_filled` crediting as the free-agent board above — an incoming
    veteran can't claim an open taxi slot, but an existing taxi stash
    still counts as spent capacity rather than reading as already over
    capacity before the trade changes anything. `reserve_filled`/
    `taxi_filled` are computed *after* removing any outgoing player who
    was themselves on IR/taxi, since trading them away genuinely frees
    that slot.
  - **Recommended cuts when over capacity** — `recommend_drop()` (the same
    lowest-value-bench-player heuristic `rank_by_marginal_value` already
    uses for forced drops elsewhere) is applied once per player over the
    limit, each cut applied before searching for the next, building
    `recommended_drops` (one entry per cut, same player_id/name/pos/
    adj_value/is_starter shape `recommend_drop` itself returns).
    `lineup_delta_after_drops` is the trade's real net lineup impact once
    those forced cuts are included — `lineup_delta` alone is the trade-only
    number and can look better than reality if making room actually costs
    a real starter, not just bench depth (a genuine possibility when
    capacity is tight enough that the "extra" roster spot was in the
    starting lineup). A newly-incoming player is never recommended as its
    own trade's forced cut — trading for someone only to immediately
    suggest dropping them again would be nonsensical; if every remaining
    over-capacity slot can only be resolved by cutting an incoming player,
    `recommended_drops` simply comes up short of the real overflow instead
    of recommending that.
  - **3-way trades aren't supported** — rare enough in practice and
    disproportionately more complex to model correctly (which two sides of
    a 3-way actually exchange which assets isn't a simple before/after
    diff the way a 2-team trade is).
  - A pick with no resolvable value (the same FantasyCalc pick-naming-mismatch
    gap `pick_trade_values` already documents) contributes `0` to that
    side's asset value, surfaced to the user rather than silently wrong.
  - **Non-obvious-value callouts** — `callouts`, a list of
    plain-text notes surfacing value the two headline deltas alone can
    miss, all composed from existing primitives (no new signal, per
    `.claude/conventions/valuation_principles.md`'s "one valuation
    strategy" rule): a weekly starting gap this trade opens or closes
    (`gap_delta()`, called in both directions — swapping before/after finds
    the "closes an existing gap" case, not just "opens a new one"; the same
    two week-lists are also returned as real data —
    `weekly_gaps_opened`/`weekly_gaps_closed` — not just formatted text, so
    `suggested_trades()` can use them as a ranking tie-break, see below); an
    incoming player who handcuffs one of this roster's own *kept* RBs
    (`handcuff_targets()` in `dynasty_core/handcuffs.py`, shared with the
    Draft Plan's identical "also handcuffs your own X" reason — a starter
    also leaving in the same trade doesn't count); an outgoing player who
    wasn't even starting here (a low real cost to give up) or an incoming
    one who'd start immediately (real value beyond raw `adj_value`), via
    the same `assign_starters()` + `ineligible_ids` filtering pattern
    `recommend_drop()` uses; and where an involved pick ranks within its
    own season's class specifically (not the whole leaguewide table), from
    `pick_trade_values()`'s own output. `handcuffs`/`outgoing_pick_names`/
    `incoming_pick_names`/`pick_value_table` are optional parameters —
    omitting them just skips the callouts that need them, so every
    pre-existing caller/test keeps working unchanged.
- **Suggested Trades** (`find_trade_offers()`, `leaguewide_trade_candidates()`,
  `suggested_trades()`) — one step earlier than the evaluator
  above, and leaguewide by default rather than requiring a hand-picked
  partner and target first. Fully decoupled from the manual evaluator's
  `your_team_id`/`partner_team_id` selectors — always scans for
  `state["user_roster_id"]`'s real roster.

  `find_trade_offers()` is the single-target primitive everything else
  composes: given one asset (player or pick, not a bundle) on a specific
  partner's roster, is it worth pursuing and what should be offered for
  it. No new valuation model (`.claude/conventions/valuation_principles.md`).
  `target_read` reuses `evaluate_trade()` with zero outgoing for the
  marginal lineup value plus market value of acquiring it for free. The
  offer search only runs once the target's value actually resolves (a
  `pd.notna()` check, not a bare `or 0.0` — see `valuation_principles.md`'s
  NaN rule) — otherwise it returns nothing rather than searching against a
  fabricated `$0` baseline. It then searches combinations (size 1–3) of the
  caller's own sellable players/picks, pruned to a plausible value band
  around the target before capping the pool
  (`TRADE_OFFER_POOL_CAP`/`PREFILTER_*` in `dynasty_core/trade.py`), and
  verifies each two-sided through `evaluate_trade()` — the one hard gate is
  the partner's own `asset_value_delta` staying within
  `TRADE_OFFER_PARTNER_TOLERANCE_PCT` of zero. Combos touching one of the
  partner's current `need_positions` rank ahead of otherwise-equal
  alternatives (a tiebreaker only, not a second gate). Returns up to
  `top_n`, empty if nothing clears the bar. `handcuffs` and
  `pick_value_table` (already required here for the offer search itself)
  pass straight through to every `evaluate_trade()` call for the same
  `callouts` the manual evaluator surfaces above.

  Scanning every partner's whole roster the naive way (every candidate on
  every other team × a full `find_trade_offers()` combo search each)
  multiplies an already-expensive single-target search by roughly the
  number of teams in the league — flagged during design as its own
  architecture question, not a small extension. Resolved with a two-stage
  split:
  - **Stage 1**, `leaguewide_trade_candidates()` — every fantasy-relevant
    player on every *other* roster, ranked by season-average marginal
    lineup value against the user's own roster via `rank_by_marginal_value`
    (the same primitive `free_agent_board` reuses, not a second valuation
    model), pre-filtered to what the user's own sellable pool could
    plausibly afford. That affordability pre-filter
    (`_max_affordable_target_value()`) matters: an unfiltered marginal-value
    ranking skews toward the league's biggest names at the user's weak
    positions — exactly the players no realistic offer from real sellable
    depth could match — which would otherwise waste Stage 2's whole search
    budget on unreachable stars. The ceiling reuses `find_trade_offers()`'s
    own `TRADE_OFFER_PREFILTER_HIGH` tolerance (the top
    `TRADE_OFFER_MAX_COMBO_SIZE` sellable assets by value, scaled), not a
    second tolerance rule. Cheap enough (one batch call, same order of
    magnitude as `free_agent_board`'s own unconditional per-refresh cost)
    to compute inside `gather_state()` every refresh, capped to
    `SUGGESTED_TRADE_SCAN_TOP_K` candidates.
  - **Stage 2**, `suggested_trades()` — the real, expensive search, but only
    for Stage 1's already-short list: calls the unmodified
    `find_trade_offers()` once per candidate, drops any with no viable
    offer, and ranks survivors primarily by their best offer's
    `lineup_delta_after_drops` — multi-season roster strength, matching this
    league's rebuild strategy, stays the primary question. Ties are broken
    by net weekly-gap improvement (weeks
    closed minus weeks opened, from the same `weekly_gaps_opened`/
    `weekly_gaps_closed` the manual evaluator's callouts already compute) —
    a real but secondary signal for when a trade is otherwise-equal on
    long-run value but meaningfully smooths over a recurring weekly hole,
    never able to outrank a genuine `lineup_delta_after_drops` difference.
    Bounded to a constant K regardless of league size — the actual answer to
    the scan-cost question, not just a smaller version of the original
    per-partner scan. Triggered by an explicit "Scan the league for offers"
    button (this part is still expensive enough to keep off the reactive
    path), unlike Stage 1's candidate list, which needs no button since it's
    already computed.

  An optional target picker sits alongside the leaguewide view — choosing
  one specific player from any other roster skips both stages and runs a
  direct single-target `find_trade_offers()` search immediately (cheap,
  reactive, same as before), resolving the owning partner automatically
  rather than requiring it be picked first. Out of scope for v1: pick
  targets (no comparable marginal-lineup signal to rank leaguewide
  candidates by — still fully usable in the manual evaluator above),
  multi-asset targets, and 3-way trades. Lives in the Trade Evaluator tab
  below the manual evaluator.
- **Improve an incoming offer** (`improve_incoming_offer()`) —
  a distinct question from the two above: a partner has *already* proposed
  a specific, fully-specified trade (both sides, potentially multiple
  assets each — players, current- or future-season picks, any mix) *to*
  the user, via the manual evaluator's own selectors. Not another
  from-scratch `find_trade_offers()`-style search — the ask is "tweak this
  real proposal," not "ignore it and search my whole pool again." Instead,
  generates single-move neighbors of the actual proposal — drop an asset,
  swap one for a candidate from that side's owner's own asset pool, or add
  a pool candidate — independently on each side (your own sellable
  players/picks for what you'd give, the partner's for what you'd
  receive). Both `find_trade_offers()` and this function draw their
  candidate pool from the same extracted `_asset_pool()` helper (sellable
  players + every owned pick, merged and value-sorted) rather than each
  reimplementing the merge.

  A variant survives only if it clears the same two gates already
  established elsewhere: the partner's `asset_value_delta` within
  `TRADE_OFFER_PARTNER_TOLERANCE_PCT`/`TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE`
  of zero (anchored to the baseline proposal's own incoming value, mirroring
  `find_trade_offers()`'s tolerance formula), and a lineup-value bar
  (`your_side["lineup_delta_after_drops"] > 0`) reused verbatim from
  `suggested_trades()`'s own "worth surfacing at all" rule
  (`valuation_principles.md`) rather than a second bar for "is this
  actually good." Returns a three-way verdict, not just a list:
  `"accept"` (the baseline is already worth taking, any variant that's
  *also* good and strictly better is optional upside), `"counter"` (the
  baseline isn't good, but at least one variant is — ranked by
  `your_side["asset_value_delta"]`, capped to `top_n`), or `"reject"`
  (nothing clears the bar — say so plainly rather than an unexplained
  empty list). Reuses the manual evaluator's own selected assets directly
  via a "Suggest an improvement" button — no separate UI selectors.
- **Bye-week impact** and **weekly gaps** — the former
  (`roster_bye_conflicts`) shows every week with an active-roster player on
  bye: who's out, who fills in, and the resulting delta to optimal
  starting-lineup value versus a full-strength week. Reuses the same
  per-week `assign_starters` machinery as `season_average_starter_value`,
  restricted to active-roster players only (taxi/reserve excluded — they
  can't actually be started to cover a bye). `starters_out` (players
  actually bumped from the lineup) is kept separate from `bench_out`
  (bye'd players who weren't starting anyway, so they don't move
  `lineup_delta`) — a bench player's bye shouldn't read as a problem just
  because it also happened. In Streamlit, each week is its own collapsible
  section: collapsed shows only `starters_out`/`fillers`/delta, expanded
  adds `bench_out` and a plain-language breakdown. An ✅/📅 cue
  distinguishes a week that's already happened from one still ahead, using
  `league["settings"]["leg"]` (Sleeper's current-week counter) — a week
  already past still shows this same roster-based projection, not a real
  result, since there's no live in-week stats feed.
  The latter (`roster_weekly_gaps`) checks, per week, whether the roster can
  actually fill its *dedicated* QB/RB/WR/TE slots (not FLEX/SUPER_FLEX,
  deliberately not modeled) — a depth signal, not a value one; the two are
  complementary.
- **Handcuffs** — NFL depth-chart-derived RB backup pairing (latest snapshot
  of `nfl_data_py`'s depth-chart feed, a time series of scrapes rather than
  a single current view). Flags whether the user already owns a starter's
  handcuff, and flags available rookies who'd handcuff the user's own
  starters. **Rookies rarely show up here pre-season** — `nfl_data_py`'s ID
  crosswalk (`nfl.import_ids()`) generally hasn't caught up with the
  incoming class yet, not a join bug; `handcuff_to` fills in gradually
  later in the year, not all at once.
- **Lineup** — the `assign_starters` breakdown exposed directly as
  its own view, with a mode switch between two different ranking
  questions, both reusing `assign_starters()`/the taxi-IR-bench split
  unchanged (`_lineup_breakdown_from_rows()` in `dynasty_core/lineup.py`):
  **By value (dynasty)** — the long-run asset-value snapshot
  (`lineup_breakdown()`), unchanged from before, still what trade/drop/
  draft-plan decisions use (see `valuation_principles.md`'s "one valuation
  strategy" rule) — not week- or injury-aware by design. **This week's
  projection** — `weekly_lineup_breakdown()`, ranking by Sleeper's own
  per-player weekly projections (`sleeper_api.get_weekly_projections()`,
  an unofficial, undocumented endpoint) dot-producted against this
  league's real `scoring_settings` (both sides already speak Sleeper's own
  stat-key vocabulary — confirmed live to line up 1:1, no crosswalk
  needed). Current week only (`league["settings"]["leg"]`), no week
  selector; degrades to an "unavailable" message rather than crashing if
  the projections fetch fails (`data_warnings`, same isolation pattern as
  byes/handcuffs). Taxi and IR players are both in `roster["players"]`
  alongside the real bench in both modes, so they're split out by
  cross-referencing `roster["taxi"]`/`roster["reserve"]` rather than left
  lumped into "bench".
- **Draft plan** — every pick the user owns this draft. Rounds already
  played show the *real* pick Sleeper recorded (retroactively scored the
  same marginal-value way), not a stale recommendation. Upcoming rounds are
  simulated assuming **no other team's picks happen in between** — "if
  these were your only remaining picks, back to back, on the board right
  now." This can't account for the other ~11 teams' behavior, so it's
  recomputed fresh on every refresh. A completed round's drop is one of four
  `drop_status` states, recovered by diffing the user's real roster across
  refreshes and persisted per draft (`dynasty_core/draft_snapshots.py`,
  `.cache/draft_snapshots_{draft_id}.json`, keyed by `league["draft_id"]`):
  **confirmed** (a real recovered drop), **confirmed_none** (confirmed the
  roster had room, nothing was dropped), **ambiguous** (two or more of the
  user's own picks completed in the same refresh gap, so which drop paired
  with which pick can't be isolated — sticky once set, never retroactively
  resolved), or **guessed** (the frontier hasn't reached this pick yet, or
  it's an upcoming round — the same cheap heuristic as before). Once a
  pick's real post-drop roster is known, later rounds simulate forward from
  that real state instead of a chain of guesses, bounding simulation drift
  to only the unconfirmed tail of the plan. Up to 2 backup alternates are
  computed per upcoming round, checked for whether picking one instead
  would open a weekly gap the primary pick doesn't (`alternate_gap_note` —
  a plain string, deliberately, so more note types can be added later
  without a redesign). Finally compares the plan's resulting roster's
  weekly gaps against the current roster's, flagging any week the full plan
  would newly break. In Streamlit, each pick is its own collapsible
  section — collapsed shows the pick, drop, and marginal value with a
  ✅/🔜 cue for completed vs. upcoming and a ⚠️ if the suggested drop is a
  current starter; expanded holds the full reasoning and that pick's own
  backup options.

## Performance

Marginal-value ranking evaluates every available candidate per round across
18 simulated weeks each — roughly 20,000 `assign_starters` calls for a
5-round plan over ~227 candidates. `free_agent_board()` runs the same
per-candidate cost with no per-round multiplication — candidates × 18 calls,
one pass, not one per round — timed directly at ~0.16s for a synthetic
400-player pool, well under the draft plan's total cost even at
free-agent-pool scale. `fc_value_by_sleeper_id()`
builds the FantasyCalc value lookup **once** per refresh and is threaded
through every function that needs it, instead of each one rebuilding it from
the raw ~475-entry list on every call. Full `gather_state()` completes in
~3.5-4s — acceptable for a manual Refresh click, not for anything tighter.
`leaguewide_trade_candidates()` (Suggested Trades' Stage 1) adds one more
`rank_by_marginal_value` batch call at the same order of magnitude as
`free_agent_board`'s — verified live against this league's real roster data
at a few seconds added to the refresh, not a step change. Stage 2
(`suggested_trades()`, the real per-candidate offer search) stays outside
`gather_state()` entirely, run on demand behind the "Scan the league for
offers" button — verified live at ~5s for `SUGGESTED_TRADE_SCAN_TOP_K` (15)
candidates.

## Known limitations (by design, not oversight)

- Draft-plan simulation assumes no other team picks in between the user's
  own picks — genuinely can't be predicted.
- Real drop attribution (`drop_status`) only cleanly isolates a single drop
  when exactly one of the user's own picks completes between two refreshes
  — the roster diff can't otherwise tell which drop paired with which pick.
  Two or more own-picks in the same refresh gap are marked `"ambiguous"`
  permanently (sticky, never retroactively resolved by a later refresh) —
  a real limitation, not a bug, given Sleeper never records which drop was
  "for" which pick.
- `roster_weekly_gaps` doesn't model FLEX/SUPER_FLEX, only dedicated slots.
- Handcuff logic and the Lineup tab's "By value" mode have no
  injury-status awareness. The "This week's projection" mode is
  a partial exception — Sleeper's own weekly projections presumably
  reflect official injury designations to whatever degree Sleeper itself
  accounts for them, but this app doesn't verify or model that directly.
- The "This week's projection" mode's scoring dot product covers ordinary
  counting stats shared between Sleeper's projections and this league's
  `scoring_settings` directly by key name, including the threshold/long-play
  categories this league scores (`rush_fd`, `rec_fd`, `rush_40p`, `rec_40p`,
  `pass_cmp_40p`) - confirmed present in a live payload check, 2026-08-28.
  `bonus_rec_te` (TE premium) is also emitted directly by Sleeper, scoped
  correctly to TEs - the earlier assumption that a global, non-league-scoped
  endpoint could never emit a position-conditional weight as its own key
  turned out to be wrong; a small explicit fallback still derives it from
  `rec` for the rare TE projection that doesn't carry a usable value (see
  `valuation_principles.md`'s "generic stat-vocabulary dot product" rule for
  the full history). **Confirmed absent**, with no fallback able to recover
  it: `pass_td_40p`, `pass_td_50p`, `rush_td_40p`, `rush_td_50p`,
  `rec_td_40p`, `rec_td_50p` - Sleeper's weekly projections carry no
  per-play-length data, so any player projected to score a long touchdown
  has those points systematically missing from "This week's projection"
  mode, permanently, for as long as this endpoint's payload shape holds.
- Handcuffs are RB-only — the standard fantasy usage of the term.
- `free_agent_board` treats every candidate as active-roster-only
  (`taxi_eligible=False`) and shows FAAB budget for context without any
  bid-sizing logic — see the "Free agents" bullet above; taxi-slot
  eligibility modeling and richer bid-sizing logic are tracked in
  `.claude/PROJECT_PLAN_DYNASTY.md`'s Roster & trade tooling section.
- `find_trade_offers` targets one asset at a time (not a bundle), and its
  need-match ranking checks the partner's roster as it stands today, not
  the hypothetical roster after the trade — see the "Suggested Trades"
  bullet above.
- Suggested Trades' leaguewide candidate list (`leaguewide_trade_candidates()`)
  is player-only — no comparable marginal-lineup signal exists to rank a
  draft pick leaguewide alongside players, so pick targets stay reachable
  only through the manual evaluator and the single-target picker's
  existing pick-search path is not offered here. Its affordability
  pre-filter is a rough top-3-assets estimate, not a guarantee any specific
  combo clears the bar — Stage 2 (`suggested_trades()`) can still return
  fewer than `top_n` results if nothing pans out.

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
| Draft type is `"linear"` (same slot order every round) | `compute_pick_ownership` | Guarded — raises `ValueError` instead of silently computing wrong pick ownership (a snake draft reverses slot order on even rounds; not implemented) | Add snake-order support if the league ever switches |
| Roster only uses QB/RB/WR/TE/FLEX/SUPER_FLEX slot types | `assign_starters`, `roster_weekly_gaps` | Any other Sleeper slot type (`WRRB_FLEX`, `REC_FLEX`, K, DEF, IDP) would be silently ignored — not assigned, not counted, no error | Extend `FLEX_ELIGIBLE_POSITIONS`/`SUPERFLEX_ELIGIBLE_POSITIONS` and the slot-processing loop for the new type |
| `POSITION_VALUE_MULTIPLIER` (`QB: 1.175`, `TE: 1.202`) | `dynasty_core/player_pools.py` | Last-resort fallback only — stale numbers only matter if the whole `player_scoring.py` enrichment fails for a refresh | Re-run `scripts/derive_position_multipliers.py`; not urgent since it's a fallback, not the primary path |
| `player_scoring.BASELINE_SCORING` (FantasyCalc's assumed scoring model) | `player_scoring.py` | The entire per-player correction ratio is only as good as this guess — FantasyCalc doesn't publish its real formula, so it can't be verified directly | No way to verify against FantasyCalc directly; revisit only if FantasyCalc publishes methodology notes, or the correction looks systematically off |
| `BASELINE_SCORING["rec"] = 1.0`, hardcoded independent of the real `ppr` sent to FantasyCalc | `player_scoring.py` | Harmless while the league stays full PPR; if PPR ever changes, the correction ratio would silently conflate the intended scoring delta with an unpriced PPR delta (`.claude/PROJECT_PLAN_DYNASTY.md`, Valuation & data accuracy) | Thread the real `ppr` value into `BASELINE_SCORING["rec"]` instead of the literal `1.0` |
| `player_scoring.QUALIFYING_VOLUME` (QB ≥200 att / RB ≥100 carries / WR ≥50 targets / TE ≥30 targets) | `player_scoring.py` | Not derived from any league rule — a manual judgment call for "enough volume to trust a personalized ratio" | Revisit only if personalized ratios look noisy for borderline players |
| `YOUNG_CORE_MAX_YOE` / `YOUNG_CORE_NEED_THRESHOLD` / `LOW_VALUE_YOUNG_AGE` / `LOW_VALUE_AGING_AGE` | `dynasty_core/roster_needs.py`, `constants.py`, `roster_value.py` | Subjective heuristics behind the rebuild-strategy "need"/"low value" flags, not derived from any league setting | Adjust by feel as the roster ages into (or out of) the rebuild window |
| `WIN_PCT_SHRINKAGE_K = 4` (games worth of shrinkage weight toward `0.5`) | `dynasty_core/power_timeline.py` | A judgment call for how fast `win_pct_shrunk` (the power/timeline read's z-scoring input, not the displayed `win_pct`) should trust a real record over the neutral prior — not derived from any league setting or statistical fit | Adjust by feel if early-season `power_score` still looks too swingy or too damped |
| `max_keepers: 1` in the league's Sleeper settings | Not modeled anywhere | Appears vestigial for a dynasty-type league (Sleeper `type: 2`) — the whole roster carries over every year, not a limited keeper count, so this setting doesn't seem to apply | Revisit only if Sleeper's dynasty/keeper interaction is ever observed to actually matter |
| `roster_id` values are a contiguous `1..num_teams` range | `_future_pick_owners` (`pick_trade_values`, `dynasty_core/picks.py`) | The only place in this codebase that treats `roster_id` as a range rather than an opaque key (needed to synthesize future pick ownership with no real draft object). Confirmed true today; a non-contiguous ID (e.g. a departed team) would silently synthesize a phantom pick | Iterate the real `rosters` list instead of a synthesized range |
| `TRADE_OFFER_POOL_CAP` (12) / `TRADE_OFFER_MAX_COMBO_SIZE` (3) / `TRADE_OFFER_PREFILTER_LOW`–`HIGH` (0.5×–2.0×) / `TRADE_OFFER_PARTNER_TOLERANCE_PCT` (15%) / `TRADE_OFFER_MIN_ABSOLUTE_TOLERANCE` (25) | `find_trade_offers`/`_asset_pool`/`improve_incoming_offer` (`dynasty_core/trade.py`) | Judgment calls bounding an offer search's candidate pool/combinatorial search and partner-acceptance gate, not derived from any league rule — sized for this league's realistic team count and per-team sellable-pool size. Shared by both `find_trade_offers()`'s combo search and `improve_incoming_offer()`'s neighbor search via the common `_asset_pool()`/tolerance formula, not two separate constants | Adjust by feel if a real sellable pool ever exceeds the cap in practice, or the tolerance reads as too loose/strict against real trade talk |
| `SUGGESTED_TRADE_SCAN_TOP_K = 15` | `leaguewide_trade_candidates`/`suggested_trades` (`dynasty_core/trade.py`) | How many of Stage 1's cheap, affordability-filtered leaguewide candidates get Stage 2's expensive real search — bounds Suggested Trades' scan cost to a constant regardless of league size, sized to the same order of magnitude as the original single-partner whole-roster scan concept | Raise if 15 candidates routinely produce fewer than 3 viable offers in practice; lower if a scan feels slow |
| A historical winning bid's comparable value is the player's *current* `adj_value`, not their value at the time of the bid | `won_bid_sample` (`dynasty_core/waiver_bids.py`) | Not reconstructable without historical roster/value snapshots this project doesn't keep. Reasonable for the short in-season windows FAAB guidance covers today; gets progressively less accurate the further back a comparable bid is from, which is exactly why extending this to prior seasons needs a recency-aware sample, not a flat pool | Revisit if bid guidance ever extends beyond the current season, or starts looking systematically off for older in-season comparables |
| `COMPARABLE_NEAREST_K = 5` / `MIN_SAME_POSITION = 3` / `MIN_COMPARABLE_SAMPLE = 3` / `COMPARABLE_MAX_DISTANCE_PCT = 0.5` / `COMPARABLE_MIN_ABSOLUTE_DISTANCE = 50.0` | `dynasty_core/waiver_bids.py` | Judgment calls sizing the FAAB bid-guidance comparable sample and its value-distance tolerance, not derived from any league rule | Adjust by feel once a full season of real bid history exists to judge against |
| `GET /projections/nfl/regular/{season}/{week}`'s path shape and its stat-key vocabulary lining up 1:1 with `league["scoring_settings"]` for ordinary counting stats | `sleeper_api.get_weekly_projections`, `dynasty_core/lineup.py`'s `_weekly_projected_points` | An undocumented, unofficial Sleeper endpoint — no contract to rely on. Confirmed live (2026-08-21, re-confirmed 2026-08-28) to return real per-stat projections in the same stat-key vocabulary this league's `scoring_settings` already uses, including the threshold/long-play categories it scores (`rush_fd`, `rec_fd`, `rush_40p`, `rec_40p`, `pass_cmp_40p`) and, contrary to an earlier assumption, `bonus_rec_te` directly (scoped correctly to TEs) — a small fallback still covers the rare TE projection missing a usable value (see `valuation_principles.md`'s "generic stat-vocabulary dot product" and "presence check on a key" rules). `pass_td_40p`/`50p`, `rush_td_40p`/`50p`, `rec_td_40p`/`50p` are confirmed permanently absent (no per-play-length data behind a weekly projection). Wrapped in its own try/except (`gather_state`) so a fetch failure degrades to a `data_warnings` entry and an "unavailable" Lineup-tab mode; a non-numeric value within a successful fetch is skipped rather than crashing | Re-verify the live response shape if the weekly-projection lineup mode ever starts looking systematically wrong; extend the position-conditional handling if `scoring_settings` ever gains another non-raw-stat weight beyond `bonus_rec_te` |
