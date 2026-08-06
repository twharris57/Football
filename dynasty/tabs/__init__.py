"""Streamlit tab renderers, split out of streamlit_app.py by tab.

A genuine Python package for the same reason `dynasty_core/` is one
(see `CLAUDE.md`) — splitting `streamlit_app.py`'s tabs into cooperating
files requires it, rather than relying on Python's implicit PEP 420
namespace-package handling. No re-exports here: callers import directly
from each submodule (`from tabs.trade_tab import render_trade_tab`).
"""
