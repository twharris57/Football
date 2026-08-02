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
interception is returned for a touchdown (`pass_int_td`), a TE reception
premium, and first-down/long-play bonuses.

`player_scoring.py` corrects for all of it, per player, wherever real NFL
history exists: for anyone with a qualifying season in the last 3 years, it
recomputes that player's own points under this league's exact
`scoring_settings` (using raw weekly stats, plus play-by-play data for the
yardage-gated long-play bonuses and the pick-six penalty, neither of which
weekly aggregates capture) and divides by their points under FantasyCalc's
assumed baseline model (an explicit, documented assumption — FantasyCalc
doesn't publish its own formula). Below the qualifying bar, a rookie with a
matched combine profile gets that position's play-style-bucket average (see
below); everyone else below the bar falls back to the flat position
average computed from that same pooled sample — `POSITION_VALUE_MULTIPLIER`
is a last-resort constant, used only if this whole enrichment fails for a
refresh. Results are cached to disk (no TTL — the underlying seasons are
historical and don't change on a clock) and recomputed only on a "force
full refresh."

`_sane_ratio()` guards every computed ratio before it's used: a
near-zero/negative pooled `baseline_points` (`<= 1.0`, which would blow the
ratio up or invert its sign) or a result outside `MULTIPLIER_BOUNDS`
(`[0.5, 2.0]`) falls back further up the chain instead — real observed
ratios land in `[1.08, 1.61]`, comfortably inside the bound, so this is a
defensive floor against a bad data pull, not a normal code path. Covered by
`tests/test_player_scoring.py` (`TestSaneRatio`).

**The correction never lowers value for RB/WR/TE, and empirically hasn't
for QB either.** For RB/WR/TE, every scoring-rule difference this league's
`scoring_settings` add on top of `BASELINE_SCORING` — first-down bonuses,
long-play bonuses, the TE premium — is strictly additive; there's no
category `real` scores that `baseline` doesn't. That makes `ratio ≥ 1` a
structural guarantee for those three positions, not an empirical
coincidence — `real_points` can never fall below `baseline_points` when
every rule difference only adds. QB is the one position with a genuine
downward term (the INT penalty and pick-six penalty exist in `real` but not
`baseline`), so a sub-1.0 ratio is theoretically possible there — nothing
in `_sane_ratio()`'s `[0.5, 2.0]` bounds would prevent it, only a ratio
below `0.5` gets rejected. It just hasn't happened: even the lowest-ratio
QB in the real 3-season pool sits at 1.23, since the 6pt-vs-4pt TD bump and
this league's higher passing-yardage rate are large, broad-based lifts that
dwarf the INT/pick-six penalty increase for any QB with real starting
volume. A QB with an extreme INT/pick-six-to-production ratio, while still
clearing the 200-attempt qualifying bar, could in principle be the first
case where `adj_value < value`.

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
replacement-level ones at the same position. Not something this project can
verify directly any more than `BASELINE_SCORING` itself can (see below);
revisit if `adj_value` ever looks systematically off at one end of a
position's range rather than uniformly.

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
reserve/IR slots). Covered by `tests/test_dynasty_core.py`
(`TestCapacityAwareDrop`). Rookies are assumed taxi-eligible for this check
(true for every candidate in this draft); a general accrued-experience
eligibility model is deferred (see `.claude/PROJECT_PLAN.md`).

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

  `_position_starter_demand()` adds `roster_positions.count("SUPER_FLEX")`
  to QB's demand specifically, matching the `num_qbs` pattern the
  market-value call already uses (`count("QB") + count("SUPER_FLEX")`) —
  in this confirmed superflex league, roughly two QBs per team are
  startable, not one, and a dedicated-slot-only count would silently
  understate QB's real replacement-level rank (12 vs. the correct ~24) and
  systematically understate QB's `vor`. FLEX demand for RB/WR/TE is **not**
  covered by this — unlike SUPER_FLEX's near-total lean toward a 2nd QB,
  FLEX splits demand across three positions with no similarly clean
  allocation; doing it properly needs a joint model of relative positional
  depth, not a simple per-position count. Same "ignores FLEX" simplification
  `roster_weekly_gaps` makes deliberately. See
  `.claude/conventions/valuation_principles.md` for the durable rule this
  follows ("superflex inflates QB value — model it as such, everywhere").
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
    is the real `wins / (wins + losses + ties)` from Sleeper's standings,
    exactly what the CLI/Streamlit "Win %" display prints; `win_pct_shrunk`
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
  also exposed, both display-only derivatives — the UI/CLI lead with "3 of
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

  A **Glossary** (`GLOSSARY` dict + an `st.dialog` in `streamlit_app.py`,
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
  string built from it, for plain-text display (the CLI). In Streamlit,
  this table renders as plain HTML (`show_status_table()`) instead of
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
  Sleeper doesn't expose, tracked in `.claude/PROJECT_PLAN.md`.
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
  simplifications, both tracked in `.claude/PROJECT_PLAN.md`:
  - **Active-roster-only capacity** — passes `taxi_eligible=False` to
    `roster_total_capacity()`/`rank_by_marginal_value()` (a new parameter,
    default `True` so the rookie draft plan's own behavior is unaffected),
    since Sleeper's real accrued-experience taxi rule isn't verified here.
    A candidate is only ever suggested for an open active slot or via a
    drop, never assumed to fit an open taxi slot the way a rookie safely
    can.
  - **No FAAB bid-sizing** — remaining budget
    (`league["settings"]["waiver_budget"] - roster["settings"].
    waiver_budget_used`, both already pulled, no new fetch) is shown for
    context only; there's no bid-amount input anywhere in this app yet for
    a threshold to apply to.
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
- **Lineup** — the `assign_starters` breakdown exposed directly as its own
  view (current-value snapshot; not week- or injury-aware yet — a planned
  refinement), with separate Starters/Bench/Taxi/IR sections
  (`lineup_breakdown()`) — taxi and IR players are both in
  `roster["players"]` alongside the real bench, so they're split out by
  cross-referencing `roster["taxi"]`/`roster["reserve"]` rather than left
  lumped into "bench".
- **Draft plan** — every pick the user owns this draft. Rounds already
  played show the *real* pick Sleeper recorded (retroactively scored the
  same marginal-value way), not a stale recommendation. Upcoming rounds are
  simulated assuming **no other team's picks happen in between** — "if
  these were your only remaining picks, back to back, on the board right
  now." This can't account for the other ~11 teams' behavior, so it's
  recomputed fresh on every refresh. Up to 2 backup alternates are computed
  per upcoming round, checked for whether picking one instead would open a
  weekly gap the primary pick doesn't (`alternate_gap_note` — a plain
  string, deliberately, so more note types can be added later without a
  redesign). Finally compares the plan's resulting roster's weekly gaps
  against the current roster's, flagging any week the full plan would newly
  break. In Streamlit, each pick is its own collapsible section — collapsed
  shows the pick, drop, and marginal value with a ✅/🔜 cue for completed vs.
  upcoming and a ⚠️ if the suggested drop is a current starter; expanded
  holds the full reasoning and that pick's own backup options.

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

## Known limitations (by design, not oversight)

- Draft-plan simulation assumes no other team picks in between the user's
  own picks — genuinely can't be predicted.
- `roster_weekly_gaps` doesn't model FLEX/SUPER_FLEX, only dedicated slots.
- Lineup and handcuff logic have no injury-status awareness.
- Handcuffs are RB-only — the standard fantasy usage of the term.
- `free_agent_board` treats every candidate as active-roster-only
  (`taxi_eligible=False`) and shows FAAB budget for context without any
  bid-sizing logic — see the "Free agents" bullet above and
  `.claude/PROJECT_PLAN.md`'s `RT-8`/`RT-10`.

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
| `POSITION_VALUE_MULTIPLIER` (`QB: 1.175`, `TE: 1.202`) | `dynasty_core.py` | Last-resort fallback only — stale numbers only matter if the whole `player_scoring.py` enrichment fails for a refresh | Re-run `scripts/derive_position_multipliers.py`; not urgent since it's a fallback, not the primary path |
| `player_scoring.BASELINE_SCORING` (FantasyCalc's assumed scoring model) | `player_scoring.py` | The entire per-player correction ratio is only as good as this guess — FantasyCalc doesn't publish its real formula, so it can't be verified directly | No way to verify against FantasyCalc directly; revisit only if FantasyCalc publishes methodology notes, or the correction looks systematically off |
| `BASELINE_SCORING["rec"] = 1.0`, hardcoded independent of the real `ppr` sent to FantasyCalc | `player_scoring.py` | `get_dynasty_values()` sends this league's real PPR to FantasyCalc, so its market value is calibrated to it — but `BASELINE_SCORING` assumes `1.0` regardless. Harmless while the league stays full PPR; if it's ever changed, the correction ratio would silently conflate the intended residual-scoring delta with an unintended PPR delta FantasyCalc's own call already priced in (`.claude/PROJECT_PLAN.md`, Valuation & data accuracy) | Thread the real `ppr` value into `BASELINE_SCORING["rec"]` instead of the literal `1.0` |
| `player_scoring.QUALIFYING_VOLUME` (QB ≥200 att / RB ≥100 carries / WR ≥50 targets / TE ≥30 targets) | `player_scoring.py` | Not derived from any league rule — a manual judgment call for "enough volume to trust a personalized ratio" | Revisit only if personalized ratios look noisy for borderline players |
| `YOUNG_CORE_MAX_YOE` / `YOUNG_CORE_NEED_THRESHOLD` / `LOW_VALUE_YOUNG_AGE` / `LOW_VALUE_AGING_AGE` | `dynasty_core.py` | Subjective heuristics behind the rebuild-strategy "need"/"low value" flags, not derived from any league setting | Adjust by feel as the roster ages into (or out of) the rebuild window |
| `WIN_PCT_SHRINKAGE_K = 4` (games worth of shrinkage weight toward `0.5`) | `dynasty_core.py` | A judgment call for how fast `win_pct_shrunk` (the power/timeline read's z-scoring input, not the displayed `win_pct`) should trust a real record over the neutral prior — not derived from any league setting or statistical fit | Adjust by feel if early-season `power_score` still looks too swingy or too damped |
| `max_keepers: 1` in the league's Sleeper settings | Not modeled anywhere | Appears vestigial for a dynasty-type league (Sleeper `type: 2`) — the whole roster carries over every year, not a limited keeper count, so this setting doesn't seem to apply | Revisit only if Sleeper's dynasty/keeper interaction is ever observed to actually matter |
| `roster_id` values are a contiguous `1..num_teams` range | `_future_pick_owners` (`pick_trade_values`) | Every other place in this codebase treats `roster_id` as an opaque key; this is the only place that assumes it's a literal range, to synthesize a future season's pick ownership without a real Sleeper draft object to read a `slot_to_roster_id` mapping from. Confirmed true for this league directly, but if Sleeper ever assigns non-contiguous IDs (e.g. after a team leaves and isn't backfilled), it would silently synthesize picks for a `roster_id` that doesn't exist | Iterate the real `rosters` list instead of a synthesized range |
