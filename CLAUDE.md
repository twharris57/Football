# Football — Claude Project Guide

## Project Overview

A personal tool for picking an NFL confidence pool (the "Legion pool" — see
`docs/confidence-pool-web-app.md` for its bylaws-derived rules), plus a
separate Sleeper dynasty league toolkit. The confidence-pool side pulls live
schedule and odds data via `nfl_data_py`, converts Vegas moneylines into
implied win probabilities, and ranks that week's games by confidence to
assign N..1 points (standard confidence-pool scoring). Both subsystems are
single-user but deployed as web services (Streamlit + Docker, on the user's
NAS) rather than run only interactively — `confidence_pool/football.py` and
`football_enhanced.py` remain as the original, standalone-only scripts.

## Active Conventions

@.claude/conventions/git_workflow_simple.md
@.claude/conventions/code_conventions.md
@.claude/conventions/python_guidelines.md
@.claude/conventions/testing.md
@.claude/conventions/web_guidelines.md
@.claude/conventions/docker_guidelines.md
@.claude/conventions/app_deployment_reference.md
@.claude/conventions/valuation_principles.md
@.claude/conventions/confidence_pool_principles.md

## Architecture

Two independent subsystems, segregated into their own top-level folders —
`confidence_pool/` (weekly NFL confidence-pool picker) and `dynasty/`
(Sleeper dynasty league tools). They share no code and don't import each
other. No real Python packaging (no `pyproject.toml`, not installable) —
modules resolve each other as flat sibling files via whichever directory
happens to be on `sys.path` at runtime (the script's own directory, added
automatically by `python`/`streamlit run`; `conftest.py` does the same
explicitly for `pytest`). `dynasty_core/` and `dynasty/tabs/` are genuine
Python packages only because splitting one large module (`dynasty_core.py`,
`streamlit_app.py`'s tabs) into cooperating files requires it — everything
else stays flat, on purpose.

- `confidence_pool/football.py` is the original, simple version: hardcoded
  year/week/gamedays, ranks games by `home_moneyline` magnitude, and prints
  an injury report for toss-up games (`|home_moneyline| < 150`).
- `confidence_pool/football_enhanced.py` is a refactor toward a pluggable
  weight-function architecture: each signal (currently only
  `compute_vegas_odds`) returns a per-game confidence score, scores are
  combined via `weight_factors`, and results are ranked and assigned points.
  Additional signals (injury impact, weather/altitude, sentiment) are
  sketched as commented-out stubs for future work.
- `confidence_pool/team_metadata_batch.py` is an early, unfinished prototype
  for enriching teams with environmental metadata (stadium altitude,
  temperature bias, play style) via the OpenWeatherMap API. It is not wired
  into either picker and still has a placeholder API key.
- `confidence_pool/football.ipynb` mirrors `football.py`'s logic as a
  notebook for interactive exploration.
- **Confidence pool web app**: `picks_core.py` is a fresh library (not a
  refactor of `football_enhanced.py`, which stays untouched as the proven
  reference implementation this reuses the math from) — current-week
  detection, the Legion pool's own game-selection rules (see "Legion pool
  sheet rules" under Domain Concepts below), Vegas-odds ranking, and the
  pick-submission deadline.
  `store.py` persists each week's evaluated games and generated picks to
  SQLite (`confidence_pool_data/picks.db`, anchored via `data_dir.py`
  mirroring `dynasty/cache_dir.py`'s pattern), locking a week once its
  deadline passes. The schema is normalized (stable reference data --
  `seasons`, `teams`, `games` -- separate from per-generation snapshots in
  `weekly_games`/`weekly_picks`) and applied via versioned migrations
  under `db_schema/` rather than one inline `CREATE TABLE` script; see
  `docs/confidence-pool-data-model.md` for the full design.
  `streamlit_app.py` + `panels/` (named to avoid colliding with
  `dynasty/tabs/` when both subsystems share a `sys.path`, e.g. under
  `pytest`) is the two-tab (Picks, Settings) web UI. Full design in
  `docs/confidence-pool-web-app.md`.
- **Dynasty league tools** (Sleeper), all under `dynasty/`: `sleeper_api.py`
  is a thin client for Sleeper's public read-only API, with local disk
  caching for the ~14MB players reference dataset (`.cache/` at the repo
  root regardless of where the code that touches it lives — see
  `cache_dir.py` — gitignored, 12h TTL). `fantasycalc_api.py` wraps
  FantasyCalc's public dynasty trade-value rankings — the market-value
  baseline, corrected for this league's non-standard scoring (see below) and
  used as an input to a marginal-lineup-value ranking, not the final answer.
  `dynasty_core/` holds all the shared logic — pick ownership, the rookie
  big board, roster analysis (needs/value/capacity/byes/weekly gaps/handcuffs),
  optimal-lineup assignment, and the round-by-round draft plan — split into
  one submodule per concern (see its own `__init__.py`), behind one
  `gather_state()` call, used by `streamlit_app.py` + `tabs/` (web
  dashboard, 5 tabs, one module per non-trivial tab). Full methodology in
  `docs/rookie-draft-big-board.md`; web/Docker details in
  `docs/dynasty-draft-web-app.md`.
- **Scout API** (`dynasty/scout_api/`): a separate, small FastAPI service
  — its own Dockerfile, `VERSION`, minimal `requirements.txt`, and GHCR
  image, deployed as a third container alongside the two Streamlit apps —
  giving the automated daily-scout's `/schedule` cloud routine (see
  `.claude/PROJECT_PLAN_DYNASTY.md`'s "Automated daily scout" section,
  `SC-11`) an HTTP surface to reach on the NAS, since a cloud routine has
  no access to local files or services. Currently a proof-of-concept
  slice only — `/health` (unauthenticated liveness) and `/ping`
  (authenticated via a shared-secret `X-Scout-Token` header, checked
  against `SCOUT_API_TOKEN`) — proving the network path and auth work
  end to end before any real findings-store endpoints (`SC-2`) are built
  on top. Deliberately not part of `dynasty_core/` or `streamlit_app.py`
  — a different deployable process with its own release cadence, not a
  Streamlit page.
- **Web + Docker**: `web_guidelines.md` applies to both Streamlit UIs
  (`dynasty/streamlit_app.py`/`dynasty/tabs/` and
  `confidence_pool/streamlit_app.py`/`confidence_pool/panels/`), and
  `docker_guidelines.md` applies to each app's own Dockerfile (root
  `Dockerfile` for dynasty, `confidence_pool/Dockerfile` for the
  confidence pool, `dynasty/Dockerfile.scout-api` for the scout API —
  ports 8501/8502/8503 respectively) plus the shared compose setup below.
  `python:3.12-slim` is used instead of the guideline's alpine default
  for all three — a deliberate exception for the two data-heavy apps,
  since `nfl_data_py`'s `fastparquet`/`cramjam` dependency often lacks
  prebuilt musl wheels (same call made in the sibling `Finance-Dashboards`
  project); the scout API has no such dependency but stays on the same
  base for consistency rather than reconciling two bases later. GitHub
  Actions (`.github/workflows/docker-publish.yml`) builds and pushes all
  three images to GHCR (`ghcr.io/twharris57/football-dynasty-draft`,
  `ghcr.io/twharris57/football-confidence-pool`,
  `ghcr.io/twharris57/football-scout-api`) on every push to `main`, via a
  build matrix. `docker-compose.deploy.yml` is this repo's deployment
  reference per `app_deployment_reference.md`, with one service per app;
  the deployment repo that reads and adapts it is `../nas-configs`
  (`football/football-compose.yaml`). Local dev (`docker-compose.yml`)
  still builds all three from source.

## Key Constraints

- `confidence_pool/football.py`/`football_enhanced.py` (the legacy CLI
  scripts only) hardcode year/week/gamedays, edited by hand each week — the
  web app (`picks_core.py`) auto-detects the current week instead.
- Fully dependent on `nfl_data_py`'s upstream data availability (schedules,
  odds, injuries); no offline fallback. The web app caches the schedule
  fetch briefly (`st.cache_data`, 15m TTL) but has no persistent cache of
  its own beyond the weekly picks/games snapshots in `store.py`.
- The late-season weeks' pick deadline (`season_week_rules`) needs manual
  correction once the commissioner announces each year's actual cutoff —
  see `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`'s `CP-1`. *Which* weeks
  count as "late season" also needs a yearly check against that year's
  real bylaws (`store.KNOWN_LATE_SEASON_WEEKS`, "Legion pool sheet rules"
  under Domain Concepts below) -- confirmed to genuinely change year to
  year, not just a hypothetical risk.
- `team_metadata_batch.py` needs a real OpenWeatherMap API key to function and
  is currently non-functional / not integrated into the picking flow.
- Dynasty tools depend on two external, unauthenticated public APIs (Sleeper,
  FantasyCalc) with no SLA. Both clients mount a `Retry` adapter (3 retries,
  exponential backoff on connection errors/429/5xx) rather than a bare
  `requests.get`, but there's still no SLA to rely on.

## Project Structure

```
confidence_pool/
  football.py              Simple standalone confidence-pool picker (moneyline ranking + injury report) - legacy, untouched
  football_enhanced.py     Weighted multi-signal picker framework (only Vegas odds active so far) - legacy, untouched
  team_metadata_batch.py   Prototype: team altitude/temperature/style enrichment via OpenWeatherMap (unintegrated)
  football.ipynb           Notebook version of football.py for interactive experimentation
  picks_core.py            Web app's core library: current-week detection, game-selection rules, Vegas-odds ranking, deadline
  store.py                 SQLite persistence: seasons/teams/games (reference data), weekly snapshots, lock-in
  db_schema/               Migration runner + versioned *.sql migrations applied by store.connect() (not "schema" - avoids colliding with the schema PyPI package)
  data_dir.py              Shared DATA_DIR/DB_PATH, anchored to the repo root (mirrors dynasty/cache_dir.py's pattern)
  streamlit_app.py         Web app entry point (thin orchestrator)
  panels/                  One module per Streamlit tab (Picks, Settings) - named to avoid colliding with dynasty/tabs/
  Dockerfile               Image for confidence_pool/streamlit_app.py (python:3.12-slim, non-root, port 8502)
dynasty/
  sleeper_api.py           Sleeper API client + local players-dataset cache
  fantasycalc_api.py       FantasyCalc dynasty trade-value client
  cache_dir.py             Shared CACHE_DIR, anchored to the repo root regardless of caller depth
  dynasty_core/            Shared dynasty logic, one submodule per concern (pick ownership, player
                            pools, roster needs, power/timeline, lineup, roster value, byes,
                            handcuffs, marginal-value ranking, trade evaluation, draft plan,
                            team analysis, orchestration) - see its __init__.py for the full map
  player_scoring.py        Per-player real-scoring correction (league scoring_settings vs. FantasyCalc's assumed baseline)
  scripts/                 One-off/derivation scripts, e.g. derive_position_multipliers.py (rookie play-style bucket ratios)
  streamlit_app.py         Rookie draft big board web dashboard entry point (thin orchestrator)
  tabs/                    One module per Streamlit tab, plus components.py for shared display helpers
  scout_api/                Separate FastAPI service (own Dockerfile/VERSION/requirements.txt) - the daily-scout's SC-11 API surface, PoC-only (/health, /ping) for now
  Dockerfile.scout-api      Image for dynasty/scout_api/app.py (python:3.12-slim, non-root, port 8503)
tests/
  dynasty_core/            pytest suite mirroring dynasty_core/'s submodules, plus helpers.py fixtures
  test_player_scoring.py
  test_scout_api.py        pytest suite for dynasty/scout_api's endpoints (FastAPI TestClient, no real network)
  confidence_pool/         pytest suite for picks_core.py and store.py (synthetic schedule data, in-memory SQLite)
Dockerfile               Image for dynasty/streamlit_app.py (python:3.12-slim, non-root, port 8501)
docker-compose.yml       Local dev: builds all three apps' images from source
docker-compose.deploy.yml  Deployment reference, one service per app (pulls prebuilt GHCR images; ../nas-configs deploys the adapted copy)
.env.example             Deployment reference env vars for docker-compose.deploy.yml (secrets left blank + a comment on source)
.github/workflows/       CI: ci.yml runs pytest on every PR; docker-publish.yml builds+pushes all three images to GHCR (matrix) on push to main
requirements.txt         Pinned dependencies (nfl_data_py, pandas, numpy, requests, streamlit, fastapi, ...) - shared by the two Streamlit apps and used to run scout_api's tests; scout_api's own Dockerfile installs from its own minimal dynasty/scout_api/requirements.txt instead
.claude/                 Claude Code conventions, commands, and one PROJECT_PLAN_<SUBSYSTEM>.md per subsystem
docs/                    Design docs for completed features, grouped by subsystem (see docs/README.md)
```

## Development Commands

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python confidence_pool/football.py            # legacy simple picker (untouched)
python confidence_pool/football_enhanced.py   # legacy weighted picker (untouched)
streamlit run confidence_pool/streamlit_app.py # confidence pool web app (port 8502)

streamlit run dynasty/streamlit_app.py # dynasty rookie draft big board, web dashboard (port 8501)

SCOUT_API_TOKEN=<any-value> uvicorn scout_api.app:app --app-dir dynasty --port 8503 # scout API PoC (SC-11)

docker compose up --build      # local: build and run all three apps in Docker

pytest tests/ -v                # ranking/lineup/valuation logic (runs in CI on every PR)
```

Test coverage is intentionally narrow so far: `tests/dynasty_core/` covers
`assign_starters`, the capacity-aware drop logic, `season_average_starter_value`'s
bye-week handling, and `roster_weekly_gaps`, one file per `dynasty_core/` submodule;
`tests/test_player_scoring.py` covers the per-player real-scoring correction's
`_sane_ratio` guard and multiplier fallback chain; `tests/test_sleeper_api.py`/
`tests/test_fantasycalc_api.py` cover each client's retry/session config and
on-disk cache TTL behavior (`_session.get` monkeypatched, no real network
calls); `tests/confidence_pool/` covers `picks_core.py`'s
game-selection/ranking/deadline logic and `store.py`'s persistence
round-trip and lock enforcement; `tests/test_scout_api.py` covers
`dynasty/scout_api`'s `/health`/`/ping` endpoints via FastAPI's
`TestClient`. All run against synthetic data or monkeypatched API
boundaries — no real API calls. The legacy confidence-pool scripts still
have none. See `testing.md` for general conventions.

## Available Skills

- `/handoff` — snapshot current session state so the next session can resume cleanly
- `/review` — pre-commit checklist before committing
- `/pr` — create or update a pull request following the project's PR conventions
- `/update-from-agentconfig` — pull upstream AgentConfig changes selectively
- `/valuation-review` — deep fantasy-stats-methodology review of the dynasty valuation
  logic on a branch/PR (or the whole pipeline), filed into `PROJECT_PLAN_DYNASTY.md` and
  `valuation_principles.md`
- `/confidence-pool-review` — deep sports-betting/reliability-methodology review of the
  confidence-pool picking logic on a branch/PR (or the whole app), filed into
  `PROJECT_PLAN_CONFIDENCE_POOL.md` and `confidence_pool_principles.md`

## Domain Concepts

- **Confidence pool**: a weekly NFL pick'em format where you assign points
  `N..1` across your picks for the week — most points on your most confident
  pick, one point on your least confident. Total points scored is what's
  compared against other players.
- **Moneyline → implied probability**: American odds converted to a win
  probability (`compute_probability` in `football_enhanced.py`); positive
  moneylines are underdogs, negative are favorites.
- **Toss-up**: a game with `|home_moneyline| < 150` — close to even money,
  where the odds alone don't strongly separate the two teams, so injury
  reports are checked as a tiebreaker (`football.py` only; the web app
  doesn't use injury data).
- **Legion pool sheet rules**: not every game in a week counts — only
  Sunday-afternoon/Monday-night games for most of the season, per the
  pool's own bylaws. The season's final few weeks flip that: every game
  that week counts (no weekday filter), because their deadline is a
  single early, commissioner-announced cutoff before all of that week's
  kickoffs rather than "before the earliest selected kickoff" — which
  specific weeks this covers is itself bylaws-defined and changes year to
  year (`store.KNOWN_LATE_SEASON_WEEKS`; confirmed 16-18 for 2026, was
  17-18 in 2025). See `docs/confidence-pool-web-app.md` for the full
  derivation and `picks_core.select_games()`/`week_deadline()` for the
  implementation.
- **Dynasty league**: keeps every player on the roster year to year (no
  re-draft) — rookies are the only new players entering the league, and only
  via the annual rookie draft.
- **Superflex**: this league's `roster_positions` includes a `SUPER_FLEX`
  slot (any of QB/RB/WR/TE eligible), on top of one dedicated `QB` slot.
  Because a second QB is startable, QBs are meaningfully scarcer and more
  valuable here than in a standard single-QB league — roughly two startable
  QBs per team, not one. Any valuation or positional-scarcity logic needs to
  account for this explicitly rather than assuming single-QB demand; see
  `.claude/conventions/valuation_principles.md`.
- **Dynasty rebuild strategy**: the user's approach since year one is to
  accumulate young talent and accept being near the bottom of the league
  short-term, aiming to be competitive within ~2-3 years. This should bias
  any recommendation logic (rookie value, trade sense) toward long-term
  asset value over immediate win-now moves. See `.claude/PROJECT_PLAN_DYNASTY.md`
  for the current state of dynasty tooling.
- **Rookie draft big board**: shows the whole incoming rookie class (drafted
  players stay listed, annotated with who took them), valued via FantasyCalc
  dynasty trade value corrected for this league's QB/TE scoring (see
  `POSITION_VALUE_MULTIPLIER` in `dynasty_core/player_pools.py`). Pick *recommendations*,
  however, don't rank by that value directly — see "Marginal lineup value"
  below.
- **Marginal lineup value**: the draft plan ranks candidates by how much
  drafting them would raise the roster's season-average optimal
  starting-lineup value (`rank_by_marginal_value`), not by raw trade value.
  This is what actually captures positional scarcity — a modest player at a
  thin position can outrank a highly valued one who wouldn't crack the
  lineup — and folds bye weeks directly into the season average rather than
  handling them as a side adjustment. Full methodology, including why
  `assign_starters`'s most-restrictive-slot-first assignment is provably
  optimal for this league's slot structure, in `docs/rookie-draft-big-board.md`.

## Agent Behavior

These apply in every session regardless of task.

### Think before coding

- State assumptions explicitly before implementing. If uncertain, ask — don't guess
  and correct later.
- If a request has multiple valid interpretations, surface them and ask which is intended.
  Don't pick silently and hope for the best.
- If a simpler approach exists than what was asked for, say so. Push back when warranted.
- If something is genuinely unclear, stop and name the confusion rather than proceeding
  on a guess.

### Define success before starting

For any non-trivial task, establish what "done" looks like before writing code:

- What will you check to know the task is complete?
- For multi-step work, state the approach and get agreement before diving in.
- Weak criteria ("make it work") require constant back-and-forth. Specific, checkable
  criteria ("the form validates and shows an error on empty submit") let you work
  independently and hand off cleanly.

If the success criteria aren't clear from the request, ask — not after you've
implemented the wrong thing.

### Introducing new libraries or frameworks

When a task requires using a library, framework, or API the project hasn't used before,
briefly explain what it does and why you're reaching for it — not a line-by-line code
walkthrough, but enough context for a developer unfamiliar with it to understand the
model and look up further detail independently.

### Bulk renames and multi-file edits

`sed` (or an equivalent blind scripted substitution) is a last resort, not a default —
reach for it only when it's genuinely the best-fitting tool for the operation and
nothing else reasonably fits. Prefer, in order: the `Edit` tool (with `replace_all` for
a single file), or `Grep` to enumerate every match first followed by per-file `Edit`
calls when a rename spans multiple files or needs different handling per occurrence.
These keep each change visible and diffable instead of applying a blind pattern sweep.
`sed` is acceptable when the substitution is truly mechanical, unambiguous, and
scoped (e.g. a fixed string across many files with no contextual judgment needed) —
not as a shortcut to avoid enumerating matches first.
