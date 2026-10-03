"""Put `dynasty/` and `confidence_pool/` on `sys.path` so tests import their flat modules, as `streamlit run` does."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "dynasty"))
sys.path.insert(0, str(Path(__file__).parent / "confidence_pool"))
