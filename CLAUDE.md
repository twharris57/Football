# Football

Personal tools, deployed as Docker containers on the user's NAS:

- **Confidence pool** (`confidence_pool/`) — ranks each week's NFL games by Vegas
  odds to assign confidence points for the "Legion pool."
- **Dynasty** (`dynasty/`) — Sleeper dynasty-league dashboard: rookie draft, roster,
  trades, free agents, plus a nightly scout routine.

## Conventions

@.claude/conventions/git_workflow_simple.md
@.claude/conventions/code_conventions.md
@.claude/conventions/python_guidelines.md
@.claude/conventions/testing.md
@.claude/conventions/web_guidelines.md
@.claude/conventions/docker_guidelines.md
@.claude/conventions/app_deployment_reference.md
@.claude/conventions/valuation_principles.md
@.claude/conventions/confidence_pool_principles.md

Open work: `.claude/PROJECT_PLAN_DYNASTY.md`, `.claude/PROJECT_PLAN_CONFIDENCE_POOL.md`.
Design docs: `docs/` (index in `docs/README.md`).

## Architecture

- **The two subsystems share no code** and never import each other.
- **No packaging.** Modules import each other as flat siblings via `sys.path` (the
  script's own directory; `conftest.py` for pytest). Only `dynasty_core/`, `tabs/`,
  `panels/`, `scout_api/`, and `trade_block_migrations/` are packages.
- **Two images** (both `python:3.12-slim` — `nfl_data_py`'s parquet deps lack musl
  wheels), built and pushed to GHCR on every push to `main`:

  | App | Entry point | Port | Version file |
  |---|---|---|---|
  | Dynasty | `dynasty/server.py` (root `Dockerfile`) | 8501 | `dynasty/VERSION` |
  | Confidence pool | `confidence_pool/streamlit_app.py` | 8502 | `confidence_pool/VERSION` |

- **Dynasty serves the scout's JSON API** (`dynasty/api.py`, under `/api`) beside the UI,
  through Streamlit's `st.App` custom routes. `server.py` wires them; the UI itself
  stays in `streamlit_app.py`.

- `docker-compose.deploy.yml`, `.env.example`, and `football.secrets.env.example` are the
  deployment reference; the deployment repo is `../nas-configs`.
- **Legacy, untouched:** `confidence_pool/football.py`, `football_enhanced.py`,
  `team_metadata_batch.py`, `football.ipynb`. The web app reuses their math but not
  their code.

## Commands

```
pip install -r requirements.txt
pytest tests/ -v                                   # runs in CI on every PR
streamlit run dynasty/server.py                    # :8501, UI + /api
streamlit run confidence_pool/streamlit_app.py     # :8502
python dynasty/scripts/daily_check.py              # scout routine's league snapshot (JSON)
docker compose up --build                          # all apps locally
```

## Key constraints

- **External data has no SLA:** `nfl_data_py`, Sleeper, FantasyCalc. Tests never hit
  the network.
- **The late-season deadline and which weeks count as "late season" change yearly**
  with the pool bylaws (`store.KNOWN_LATE_SEASON_WEEKS`). Check them every season.

## Domain terms

- **Confidence pool:** assign points N..1 across a week's picks, most to the surest.
- **Legion pool selection:** most weeks only Sunday-afternoon and Monday games count,
  and the deadline is the first selected kickoff. In late-season weeks every game counts,
  with a single commissioner-set deadline.
- **Superflex:** one QB slot plus a `SUPER_FLEX` slot, so QBs are about twice as scarce.
- **Dynasty rebuild:** the user is building for 2–3 years out. Favor long-term asset
  value over win-now moves.
- **Marginal lineup value:** rank candidates by how much they raise the roster's
  season-average optimal lineup, not by raw trade value.

## Working style

- State assumptions and ask when a request is ambiguous; push back if there's a simpler way.
- Agree on what "done" means before non-trivial work.
- Briefly explain any library new to the project.
- For multi-file renames, grep first and edit per file; `sed` only for truly mechanical swaps.
