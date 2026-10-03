# Valuation Principles

Domain rules for dynasty valuation (`dynasty/dynasty_core/`, `player_scoring.py`,
`fantasycalc_api.py`). Generic lessons live in `code_conventions.md`; the methodology
itself is in `docs/rookie-draft-big-board.md`.

- **One ranking path.** Reuse `rank_by_marginal_value`, `positional_strength_summary`'s
  `vor`, and `season_average_starter_value`. Extend them; never add a parallel scorer.
- **Superflex means ~2 startable QBs per team.** Any positional demand count starts from
  `roster_positions` and counts `SUPER_FLEX` toward QB (see `_position_starter_demand()`).
- **Signals aren't actions.** Dedicated-slot-only counts (FLEX ignored for RB/WR/TE) and
  display cutoffs like `PHASE_THRESHOLDS` are fine for labels. Re-validate them before
  they drive a sell/drop/add/start recommendation.
- **Taxi/IR players never start.** Filter them out before every `assign_starters()`
  call — or reuse `recommend_drop()`/`best_position_relevant_drop()`, which already do.
- **Closing a slot to new entrants doesn't erase current occupants.** A veteran can't
  use an open taxi slot, but filled taxi slots still count as spent capacity.
- **Draftable rookies aren't free agents** while the draft has picks left.
- **Pull league rules live; document what you can't.** Hardcoded guesses (e.g.
  `BASELINE_SCORING`) get a comment and a row in the big-board doc's Static assumptions
  table, and keep the raw value beside the corrected one (`value` / `adj_value`).
- **Mirror `_stat_points()` for position-conditional scoring.** A generic
  `stat × scoring_settings` sum misses weights like `bonus_rec_te` — but only add them
  when the projection payload doesn't already include a usable value.
- **Week-indexed lists start from the live week** (`league["settings"]["leg"]`) before
  being capped.
- **Comparable-bid searches need a count floor *and* a distance floor**, and show each
  comparable's value. Never mix QB and non-QB comparables — superflex prices QBs apart.
- **Fairness tolerances anchor on the side that isn't changing** in that search direction.
- **Shrinkage constants match the quantity they weight.** A single-season threshold isn't
  the right `k` for a multi-season total.
- **Say "newly available," not "just signed,"** when the history only tracks free agents.
