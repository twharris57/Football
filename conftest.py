"""Anchors pytest's rootdir so tests/ can import project modules (dynasty_core, etc.)
regardless of how pytest is invoked (bare `pytest`, `python -m pytest`, different CWD).

Without this, `pytest tests/` fails to import dynasty_core - pytest's default
rootdir insertion adds tests/ itself (no __init__.py there) to sys.path, not
the repo root, since there's nothing here anchoring it. `python -m pytest`
worked locally by coincidence (the -m flag adds the CWD to sys.path), which
is why this only surfaced in CI.
"""
