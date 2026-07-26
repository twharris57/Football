# Football

A personal toolkit for two things: picking an NFL confidence pool, and managing
a Sleeper dynasty fantasy football team.

- **Confidence pool picker** — pulls schedule, odds, and injury data via
  `nfl_data_py` and ranks each week's games by confidence to assign points.
  See `football.py` and `football_enhanced.py`.
- **Dynasty league tools** — pulls league data from the Sleeper API to help
  with rookie drafts and trade decisions during a multi-year rebuild. In
  progress on `feature/rookie-draft-strategy`.

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
