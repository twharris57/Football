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
- `web_guidelines.md` and `docker_guidelines.md` are imported for completeness
  but don't currently apply — there's no web frontend or containerization yet.

## Key Constraints

- Year/week/gamedays are hardcoded per script and must be edited by hand each
  week — there's no CLI argument parsing yet.
- Fully dependent on `nfl_data_py`'s upstream data availability (schedules,
  odds, injuries); no offline fallback or caching.
- `team_metadata_batch.py` needs a real OpenWeatherMap API key to function and
  is currently non-functional / not integrated into the picking flow.

## Project Structure

```
football.py              Simple standalone confidence-pool picker (moneyline ranking + injury report)
football_enhanced.py     Weighted multi-signal picker framework (only Vegas odds active so far)
team_metadata_batch.py   Prototype: team altitude/temperature/style enrichment via OpenWeatherMap (unintegrated)
football.ipynb           Notebook version of football.py for interactive experimentation
requirements.txt         Pinned dependencies (nfl_data_py, pandas, numpy, requests, ...)
.claude/                 Claude Code conventions and commands
```

## Development Commands

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

python football.py            # simple picker
python football_enhanced.py   # weighted picker
```

No test suite exists yet. See `testing.md` for conventions to apply once tests
are added.

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
