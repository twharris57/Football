# Football

Personal tools for an NFL confidence pool and a Sleeper dynasty league.

- **Legion Pool** (`confidence_pool/`) — ranks each week's games by Vegas odds and
  assigns confidence points. Streamlit app on port 8502.
- **Fantasy Tools** (`dynasty/`) — rookie draft, roster, trade, and free-agent tools for a
  superflex dynasty rebuild. Streamlit app on port 8501.

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run dynasty/server.py
```

More: [`CLAUDE.md`](CLAUDE.md) (architecture and commands), [`docs/`](docs/README.md)
(design), `.claude/PROJECT_PLAN_*.md` (open work).
