# Project Plan

Tracks what's actively being worked on, what's queued up next, and longer-range
ideas for this project. When a task is completed, write it up as a design doc
in `docs/` (what was built and why, key decisions) and remove it from this file.

## Active

- **Rookie draft big board + web dashboard** (branch: `feature/bye-handcuff-flags`,
  PR #2 open against `main`) — full writeup in `docs/rookie-draft-big-board.md`
  (logic/methodology) and `docs/dynasty-draft-web-app.md` (Streamlit + Docker).
  Since Phase 0 merged (PR #1), this branch added: bye-week conflicts,
  RB handcuffs (NFL depth-chart-derived), weekly dedicated-slot gap
  detection, a QB/TE valuation correction computed from real 2024 season
  stats (resolves the explainability/scoring-mismatch gap noted below —
  no longer an open item), an optimal-lineup ("Lineup") view, and a
  complete rewrite of pick ranking from raw trade value to season-average
  **marginal** starting-lineup value (bye-adjusted), with backup
  alternates per round. The old separate "Strategy" tab was removed after
  it turned out to disagree with the round-by-round plan on what to pick
  next — merged into one consistent algorithm.
  Remaining before this is fully "done": merge PR #2, deploy to the
  Synology NAS, and — the real test — use it through the actual live
  draft (this Sunday) to see whether the recommendations hold up in the
  moment. Revisit this item afterward; it may still be worth a few
  post-draft observations even once merged.

## Future Ideas

- **Trade targets & sells** — given the rebuild strategy, flag which of the
  user's veterans are sellable for picks, and which other teams' picks/young
  players might be realistically available.
- **League-wide power/timeline read** — place every team in the league on a
  rebuild-vs-contend spectrum, to identify good trade partners (contenders who
  overpay for immediate help, rebuilders who overpay for future assets).
- **Free agent / roster-moves evaluator** — a tool for right-now decisions
  outside the draft: which available free agents are worth an add, and which
  current roster players are droppable, given the rebuild timeline.
- **Full per-player scoring recompute** — replace the QB/TE position-level
  correction (see Valuation approach below) with real per-player fantasy
  points computed from `nfl_data_py` raw stats under this league's exact
  `scoring_settings`, including the long-TD/first-down bonuses the current
  correction doesn't reach. A bigger lift than the targeted fix, deliberately
  deferred past this draft.

## Context

- Dynasty league (keep all players year to year; rookies only enter via the
  rookie draft).
- User's strategy since year one: accumulate young talent, accept being
  near the bottom of the league short-term, aiming to be competitive within
  ~2-3 years.

### Valuation approach and its remaining gaps

Player/rookie value starts from FantasyCalc's public dynasty rankings
(`fantasycalc_api.py`) — this project has no full valuation model of its
own. FantasyCalc's API only lets us tune for superflex (`numQbs=2`), league
size (`numTeams=12`), and PPR (`ppr=1.0`); it has no parameter for this
league's other non-standard scoring settings, so its raw rankings are a
generic superflex-PPR model, not this league's actual scoring. As of PR #2,
the two largest gaps are corrected (see `docs/rookie-draft-big-board.md`
for the full methodology):

- ✅ **6-point passing touchdowns** (`pass_td: 6.0`) — corrected via
  `POSITION_VALUE_MULTIPLIER["QB"]` (1.164×, computed from real 2024 stats).
- ✅ **TE premium** (`bonus_rec_te: 0.5`) — corrected via
  `POSITION_VALUE_MULTIPLIER["TE"]` (1.204×, same methodology).
- ⏳ **Still uncorrected**: bonus points for long touchdowns (40+/50+ yard,
  rush/pass/rec) and a first-down bonus (`rush_fd`/`rec_fd: 0.5`) — smaller
  effects than the two above, not yet isolated the way QB/TE were. A real
  per-player recompute from raw stats (see Future Ideas) would replace this
  whole correction with something exact instead of a position-level
  multiplier.
- Not a scoring setting, but relevant to roster/pick strategy: taxi squad is
  unusually generous (5 slots, 3 years) vs. typical dynasty leagues — more
  room to stash rookies without a roster crunch.

Ranking itself no longer uses raw (or even corrected) player value directly —
picks are ranked by season-average **marginal starting-lineup value**, which
inherently accounts for positional scarcity without needing a separate
needs-flag override. See `docs/rookie-draft-big-board.md`.
