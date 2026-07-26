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

  **Before Sunday's draft** (found in a pre-draft review, 2026-07-26):
  - 🔴 **Drop recommendation ignores open roster/taxi capacity** —
    `recommend_drop()` always forces a drop for every candidate in
    `multi_round_plan`/`rank_by_marginal_value`, even when
    `roster_capacity()` shows open active or taxi slots. The taxi squad is
    deliberately generous (5 slots, 3 years) specifically so rookies can be
    stashed without a roster crunch, so this both understates early-pick
    marginal value and can recommend cutting a real asset that didn't need
    to go. Highest-priority fix — affects every row of the Draft Plan tab.
    Thread `roster_capacity` (and ideally taxi-eligibility — see Future
    Ideas) into the drop decision so a drop is only forced when there's
    genuinely no open slot for the position being added.
  - 🟠 **No retry/backoff or error handling around live API calls** —
    `sleeper_api._get()` raises on any non-2xx/connection error;
    `rookie_draft.py`'s interactive refresh loop has no try/except, so one
    Sleeper hiccup mid-draft (plausible — everyone hits the API at once on
    draft day) kills the whole CLI session, not just one refresh. Streamlit
    catches at the top level but still has no retry. Wrap the CLI loop's
    `gather_state()` call in try/except-and-reprompt; add a retry-backed
    `requests.Session` to both API clients.
  - 🟠 **No automated tests on the core ranking algorithm** —
    `assign_starters`, `season_average_starter_value`,
    `rank_by_marginal_value` are non-trivial custom logic about to be
    trusted live for real roster decisions, with nothing to catch a
    regression (including from the capacity fix above) before the draft
    rather than during it. Even 3-4 targeted `pytest` cases (known roster →
    known `assign_starters` output; drop-capacity behavior) would be worth
    the time.
  - 🟡 **No "picks until your turn" indicator** — small addition to the
    Draft Plan tab, meaningfully improves usability on a phone mid-draft.

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
- **API resilience (retry/backoff)** — belongs as a permanent fix, not just a
  pre-draft patch (see Active, above); `sleeper_api.py`/`fantasycalc_api.py`
  currently do a bare `requests.get` with no retry on either.
- **Automated test coverage** — `dynasty_core.py`'s ranking/lineup logic has
  no tests today (see Active, above, for the minimum pre-draft slice);
  worth building out properly once the draft-week time pressure is off.
- **Taxi-squad eligibility modeling** — `roster_capacity`'s taxi slot count
  doesn't check Sleeper's accrued-experience taxi-eligibility rule, so a
  drop/no-drop decision (see Active, above) could still assume taxi room a
  specific player isn't actually eligible for. Fold in alongside the
  capacity fix rather than as a separate pass.
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
