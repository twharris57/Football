# Football — Claude Project Guide

## Project Overview

A personal tool for picking an NFL confidence pool. It pulls live schedule, odds,
and injury data via `nfl_data_py`, converts Vegas moneylines into implied win
probabilities, and ranks that week's games by confidence to assign N..1 points
(standard confidence-pool scoring). Single user, run locally and interactively —
not a deployed service.

## Active Conventions

@.claude/conventions/git_workflow_simple.md
@.claude/conventions/code_conventions.md
@.claude/conventions/python_guidelines.md
@.claude/conventions/testing.md
@.claude/conventions/web_guidelines.md
@.claude/conventions/docker_guidelines.md

## Architecture

- Plain Python scripts, no package structure, no persistence layer — everything
  is pulled fresh from `nfl_data_py` into pandas DataFrames each run.
- `football.py` is the original, simple version: hardcoded year/week/gamedays,
  ranks games by `home_moneyline` magnitude, and prints an injury report for
  toss-up games (`|home_moneyline| < 150`).
- `football_enhanced.py` is a refactor toward a pluggable weight-function
  architecture: each signal (currently only `compute_vegas_odds`) returns a
  per-game confidence score, scores are combined via `weight_factors`, and
  results are ranked and assigned points. Additional signals (injury impact,
  weather/altitude, sentiment) are sketched as commented-out stubs for future work.
- `team_metadata_batch.py` is an early, unfinished prototype for enriching teams
  with environmental metadata (stadium altitude, temperature bias, play style)
  via the OpenWeatherMap API. It is not wired into either picker and still has
  a placeholder API key.
- `football.ipynb` mirrors `football.py`'s logic as a notebook for interactive
  exploration.
- **Dynasty league tools** (Sleeper): `sleeper_api.py` is a thin client for
  Sleeper's public read-only API, with local disk caching for the ~14MB
  players reference dataset (`.cache/`, gitignored, 12h TTL). `fantasycalc_api.py`
  wraps FantasyCalc's public dynasty trade-value rankings — the market-value
  baseline, corrected for this league's non-standard scoring (see below) and
  used as an input to a marginal-lineup-value ranking, not the final answer.
  `dynasty_core.py` holds all the shared logic — pick ownership, the rookie
  big board, roster analysis (needs/value/capacity/byes/weekly gaps/handcuffs),
  optimal-lineup assignment, and the round-by-round draft plan — behind one
  `gather_state()` call, used by both `rookie_draft.py` (CLI, interactive
  refresh loop) and `streamlit_app.py` (web dashboard, 4 tabs). Full
  methodology in `docs/rookie-draft-big-board.md`; web/Docker details in
  `docs/dynasty-draft-web-app.md`.
- **Web + Docker**: `web_guidelines.md` now applies to `streamlit_app.py`, and
  `docker_guidelines.md` applies to the `Dockerfile`/compose setup below.
  `python:3.12-slim` is used instead of the guideline's alpine default — a
  deliberate exception, since `nfl_data_py`'s `fastparquet`/`cramjam`
  dependency often lacks prebuilt musl wheels (same call made in the sibling
  `Finance-Dashboards` project). GitHub Actions (`.github/workflows/docker-publish.yml`)
  builds and pushes the image to GHCR (`ghcr.io/twharris57/football-dynasty-draft`)
  on every push to `main`; the Synology NAS deployment (`docker-compose.deploy.yml`)
  only ever pulls that prebuilt image, it never builds on-device. Local dev
  (`docker-compose.yml`) still builds from source.

## Key Constraints

- Year/week/gamedays are hardcoded per script and must be edited by hand each
  week — there's no CLI argument parsing yet (confidence pool scripts only;
  the dynasty tools do take CLI args).
- Fully dependent on `nfl_data_py`'s upstream data availability (schedules,
  odds, injuries); no offline fallback or caching.
- `team_metadata_batch.py` needs a real OpenWeatherMap API key to function and
  is currently non-functional / not integrated into the picking flow.
- Dynasty tools depend on two external, unauthenticated public APIs (Sleeper,
  FantasyCalc) with no SLA — no retry/backoff logic exists yet.

## Project Structure

```
football.py              Simple standalone confidence-pool picker (moneyline ranking + injury report)
football_enhanced.py     Weighted multi-signal picker framework (only Vegas odds active so far)
team_metadata_batch.py   Prototype: team altitude/temperature/style enrichment via OpenWeatherMap (unintegrated)
football.ipynb           Notebook version of football.py for interactive experimentation
sleeper_api.py           Sleeper API client + local players-dataset cache
fantasycalc_api.py       FantasyCalc dynasty trade-value client
dynasty_core.py          Shared dynasty logic: big board, roster analysis, lineup, marginal-value draft plan
rookie_draft.py          Rookie draft big board CLI, with interactive refresh loop
streamlit_app.py         Rookie draft big board web dashboard (same logic as the CLI)
Dockerfile               Image for streamlit_app.py (python:3.12-slim, non-root)
docker-compose.yml       Local dev: builds the image from source
docker-compose.deploy.yml  NAS deploy: pulls the prebuilt GHCR image, never builds on-device
.env.example             Template for docker-compose.deploy.yml's HOST_PORT
.github/workflows/       CI: docker-publish.yml builds+pushes to GHCR on push to main
requirements.txt         Pinned dependencies (nfl_data_py, pandas, numpy, requests, streamlit, ...)
.claude/                 Claude Code conventions, commands, and PROJECT_PLAN.md
docs/                    Design docs for completed features
```

## Development Commands

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python football.py            # simple picker
python football_enhanced.py   # weighted picker

python rookie_draft.py         # dynasty rookie draft big board, interactive refresh loop
python rookie_draft.py --once  # one snapshot, no prompt

streamlit run streamlit_app.py # dynasty rookie draft big board, web dashboard

docker compose up --build      # local: build and run the dashboard in Docker

pytest tests/ -v                # dynasty_core.py's ranking/lineup logic (runs in CI on every PR)
```

Test coverage is intentionally narrow so far: `tests/test_dynasty_core.py` covers
`assign_starters`, the capacity-aware drop logic, `season_average_starter_value`'s
bye-week handling, and `roster_weekly_gaps`, all against synthetic data (no real
API calls). The confidence-pool scripts and the Sleeper/FantasyCalc clients
themselves still have none. See `testing.md` for general conventions.

## Available Skills

- `/handoff` — snapshot current session state so the next session can resume cleanly
- `/review` — pre-commit checklist before committing
- `/pr` — create or update a pull request following the project's PR conventions
- `/update-from-agentconfig` — pull upstream AgentConfig changes selectively

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
  reports are checked as a tiebreaker.
- **Dynasty league**: keeps every player on the roster year to year (no
  re-draft) — rookies are the only new players entering the league, and only
  via the annual rookie draft.
- **Dynasty rebuild strategy**: the user's approach since year one is to
  accumulate young talent and accept being near the bottom of the league
  short-term, aiming to be competitive within ~2-3 years. This should bias
  any recommendation logic (rookie value, trade sense) toward long-term
  asset value over immediate win-now moves. See `.claude/PROJECT_PLAN.md`
  for the current state of dynasty tooling.
- **Rookie draft big board**: shows the whole incoming rookie class (drafted
  players stay listed, annotated with who took them), valued via FantasyCalc
  dynasty trade value corrected for this league's QB/TE scoring (see
  `POSITION_VALUE_MULTIPLIER` in `dynasty_core.py`). Pick *recommendations*,
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
