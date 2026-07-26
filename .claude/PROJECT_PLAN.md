# Project Plan

Tracks what's actively being worked on, what's queued up next, and longer-range
ideas for this project. When a task is completed, write it up as a design doc
in `docs/` (what was built and why, key decisions) and remove it from this file.

## Active

- **Pre-draft hardening** (branch: `feature/pre-draft-hardening`, off `main`
  after PR #1 + PR #2 both merged) — addresses all four items from the
  2026-07-26 pre-draft review:
  - ✅ **Capacity-aware drop logic** — `rank_by_marginal_value()` was
    calling `recommend_drop()` unconditionally for every candidate, even
    with open roster/taxi capacity, understating marginal value and
    risking an unnecessary cut. New `roster_total_capacity()` (active
    roster slots + taxi slots) gates it: a drop is only simulated once the
    roster is genuinely full. Regression-covered in
    `tests/test_dynasty_core.py::TestCapacityAwareDrop`.
  - ✅ **API retry/backoff + CLI error handling** — `sleeper_api.py` and
    `fantasycalc_api.py` now use a `requests.Session` with a `Retry`
    adapter (3 retries, backoff, GET-only); the CLI's interactive loop
    wraps `gather_state()` in try/except with a retry/quit prompt instead
    of crashing on one hiccup. Verified by simulating a `ConnectionError`
    on the first call and confirming the loop recovers.
  - ✅ **Automated test coverage** — `tests/test_dynasty_core.py` (new,
    pytest) covers `assign_starters`, the capacity-aware drop logic,
    `season_average_starter_value`'s bye-week handling, and
    `roster_weekly_gaps`. `.github/workflows/ci.yml` (new) runs it on
    every PR to `main`.
  - ✅ **Picks-until-your-turn indicator** — `picks_until_turn()`, shown
    in both the CLI and Streamlit on-the-clock line.
  Full writeup in `docs/rookie-draft-big-board.md` (logic) and
  `docs/dynasty-draft-web-app.md` (resilience/CI). Remaining before the
  overall dashboard effort is "done": deploy to the Synology NAS and — the
  real test — use it through the actual live draft (this Sunday). The
  *next* feature branch will explore a better valuation algorithm (see
  Future Ideas: full per-player scoring recompute) rather than more
  pre-draft fixes — this branch is meant to be the stability checkpoint.

## Future Ideas

- **Trade targets & sells** — given the rebuild strategy, flag which of the
  user's veterans are sellable for picks, and which other teams' picks/young
  players might be realistically available.
- **League-wide power/timeline read** — place every team in the league on a
  rebuild-vs-contend spectrum, to identify good trade partners (contenders who
  overpay for immediate help, rebuilders who overpay for future assets).
- **Free agent / roster-moves evaluator** — a tool for right-now decisions
  outside the draft: which available free agents are worth an add, and which
  current roster players are droppable, given the rebuild timeline. Should
  extend to **in-season pickup monitoring**: when a free agent's situation
  changes materially — signs with a new team, wins a starting job, a
  depth-chart move opens up volume — score their marginal value against the
  current roster the same way the draft plan does (season-average marginal
  starting-lineup value, not raw trade value) and flag it when it would
  actually crack the lineup or clearly outvalue a bench/taxi piece worth
  cutting. This reuses `rank_by_marginal_value`/`recommend_drop` almost as-is
  once free agents are the candidate pool instead of the rookie class — the
  main new inputs are pulling league free agents from Sleeper and some
  signal for "something changed" (a depth-chart delta week over week would
  probably be enough to start; no need for a news/transactions feed on day
  one). Ties into injury-status awareness too, since a starter's injury is
  often exactly what opens the depth-chart move worth reacting to.
- **Broader test coverage** — `tests/test_dynasty_core.py` covers the
  core ranking/lineup logic (see Active, above, for what's in), but
  `sleeper_api.py`/`fantasycalc_api.py` (the retry/session logic itself),
  the CLI's error-handling loop, and most of `dynasty_core.py`'s smaller
  helpers (bye weeks, handcuffs, roster needs) still have none. Worth
  building out once draft-week time pressure is off.
- **Taxi-squad eligibility modeling** — `roster_total_capacity()` assumes
  every candidate is taxi-eligible, true for this draft's rookies but not
  a general accrued-experience eligibility check against Sleeper's actual
  taxi rule. Fold in whenever this needs to handle non-rookie candidates
  (e.g. the free-agent evaluator idea above) rather than as a separate pass.
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
