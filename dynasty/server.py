"""Dynasty server entry point: the Streamlit UI plus the scout's `/api` routes.

    streamlit run server.py
"""

from __future__ import annotations

import os

import api
import trade_block_store
from streamlit.starlette import App

app = App(
    "streamlit_app.py",
    routes=api.routes(trade_block_store.DB_PATH, os.environ.get("SCOUT_API_TOKEN")),
)
