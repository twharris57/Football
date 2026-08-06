# Football

A personal toolkit for two things: picking an NFL confidence pool, and managing
a Sleeper dynasty fantasy football team.

- **Confidence pool picker** (`confidence_pool/`) — pulls schedule, odds, and
  injury data via `nfl_data_py` and ranks each week's games by confidence to
  assign points. See `confidence_pool/football.py` and
  `confidence_pool/football_enhanced.py`.
- **Dynasty league tools** (`dynasty/`) — pulls league data from Sleeper and
  FantasyCalc to help with rookie drafts, roster/trade decisions, and a
  league-wide power/timeline read during a multi-year rebuild. Available as
  a CLI (`dynasty/rookie_draft.py`) and a Streamlit web dashboard
  (`dynasty/streamlit_app.py`), deployable via Docker.

## Setup

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## More detail

- [`CLAUDE.md`](CLAUDE.md) — architecture, conventions, and how this repo is
  organized, for both humans and AI agents working in it.
- [`.claude/PROJECT_PLAN.md`](.claude/PROJECT_PLAN.md) — what's actively being
  worked on, what's next, and future ideas.
- [`docs/`](docs/) — design docs for completed features.
