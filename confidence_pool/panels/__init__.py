"""Streamlit tab renderers, split out of streamlit_app.py by tab.

Mirrors dynasty/tabs/'s package-per-app pattern (see CLAUDE.md) -- named
`panels`, not `tabs`, specifically so the two subsystems' packages don't
collide when both end up on sys.path at once (e.g. the shared pytest
session via conftest.py) -- in production each Streamlit app only ever has
its own directory on sys.path, but bare top-level package names still need
to be unique across subsystems for anything that imports both in-process.
No re-exports here, callers import directly from each submodule.
"""
