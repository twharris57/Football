"""Puts dynasty/ and confidence_pool/ on sys.path so tests/ can import each
subsystem's modules (dynasty_core, sleeper_api, picks_core, store, ...) as
flat sibling modules, regardless of how pytest is invoked (bare `pytest`,
`python -m pytest`, different CWD).

This repo deliberately has no real Python package structure - modules
resolve each other via whichever directory happens to be on sys.path at
runtime, the same way `streamlit run dynasty/streamlit_app.py` or
`python dynasty/rookie_draft.py` auto-add dynasty/ (and, for the
confidence pool, `streamlit run confidence_pool/streamlit_app.py`
auto-adds confidence_pool/) by virtue of it being the directory the
entry-point script lives in. pytest has no equivalent "directory of the
script being run" to anchor on, so this does it explicitly instead of
relying on pytest's own conftest-directory sys.path insertion (which
anchors to repo root, not either subsystem's own directory, and was a
confusing enough implicit mechanism to warrant this explicit version).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "dynasty"))
sys.path.insert(0, str(Path(__file__).parent / "confidence_pool"))
