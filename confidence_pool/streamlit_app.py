"""Streamlit dashboard for the Legion confidence pool's weekly picks.

    streamlit run confidence_pool/streamlit_app.py

Two tabs: Picks (this week's Vegas-odds-ranked recommendation, regenerable
until the pool's deadline, then locked read-only) and Settings (season
configuration -- weeks 17/18's commissioner-announced cutoff, active
season). See docs/confidence-pool-web-app.md for the full design.
"""

from __future__ import annotations

import os
from datetime import datetime

import streamlit as st
from data_dir import DATA_DIR, DB_PATH
from panels.picks_tab import render_picks_tab
from panels.settings_tab import render_settings_tab
from picks_core import ET, default_season_year

import store

APP_VERSION = os.environ.get("GIT_SHA", "dev")[:7]

st.set_page_config(page_title="Confidence Pool", layout="centered")

DATA_DIR.mkdir(parents=True, exist_ok=True)
conn = store.connect(str(DB_PATH))

today = datetime.now(ET).date()
active_season = store.get_active_season(conn) or default_season_year(today)

st.title("Legion Confidence Pool")
st.caption(f"{active_season} season")

tab_picks, tab_settings = st.tabs(["Picks", "Settings"])
with tab_picks:
    render_picks_tab(conn, active_season, today)
with tab_settings:
    render_settings_tab(conn, active_season)

st.divider()
st.caption(f"Legion Confidence Pool · build {APP_VERSION}")
