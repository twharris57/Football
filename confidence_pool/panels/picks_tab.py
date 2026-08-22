"""Picks tab: this week's game-selection review, Vegas-odds ranking, and the
pool's lock-in deadline. See docs/confidence-pool-web-app.md for the rules.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime

import pandas as pd
import streamlit as st

import picks_core as pc
import store


@st.cache_data(ttl="15m", show_spinner="Fetching schedule...")
def _cached_schedule(year: int) -> pd.DataFrame:
    return pc.get_schedule(year)


def render_picks_tab(conn: sqlite3.Connection, active_season: int, today: date) -> None:
    try:
        schedule = _cached_schedule(active_season)
    except OSError as exc:
        st.error(f"Couldn't fetch the schedule from nfl_data_py: {exc}. Try reloading the page.")
        st.stop()
    default_week = pc.current_week(schedule, today)

    col_season, col_week = st.columns(2)
    with col_season:
        season = int(
            st.number_input(
                "Season", min_value=2020, max_value=2100, value=active_season, step=1
            )
        )
    with col_week:
        week = int(st.number_input("Week", min_value=1, max_value=18, value=default_week, step=1))

    if season != active_season:
        try:
            schedule = _cached_schedule(season)
        except OSError as exc:
            st.error(f"Couldn't fetch the schedule from nfl_data_py: {exc}. Try reloading the page.")
            st.stop()

    auto_games = pc.select_games(schedule, season, week)
    if auto_games.empty:
        st.warning(f"No games matched the pool's selection rules for week {week}.")
        return

    config = store.get_season_config(conn, season) or {}
    configured_deadline = None
    if week in (17, 18) and config.get(f"week{week}_deadline"):
        configured_deadline = datetime.fromisoformat(config[f"week{week}_deadline"])
    deadline = pc.week_deadline(auto_games, week, configured_deadline)

    saved_games, saved_picks, status = store.load_week(conn, season, week)
    included_map = (
        dict(zip(saved_games["game_id"], saved_games["included"].astype(bool)))
        if not saved_games.empty
        else {}
    )

    now = datetime.now(pc.ET)
    locked = bool(status and status["locked"])

    if not locked and pc.is_locked(now, deadline):
        # Deadline just passed with nothing explicitly locked yet -- lock the
        # last-generated snapshot (or, absent that, one final computed
        # recommendation) now rather than leaving it open to further edits.
        outcome = pc.resolve_week_lock(auto_games, included_map, saved_games, saved_picks)
        if outcome.warning:
            st.warning(outcome.warning)
        if outcome.locked:
            store.save_week(conn, season, week, outcome.games, outcome.picks, now, lock=True)
            saved_games, saved_picks, status = store.load_week(conn, season, week)
            locked = True

    st.caption(f"Pick deadline: {deadline.strftime('%a %b %d, %I:%M %p ET')}")

    if locked:
        st.success(f"Week {week} picks are locked (final as of {status['locked_at']}).")
        _render_picks_table(saved_games, saved_picks)
        return

    st.write("Games evaluated this week — uncheck any that shouldn't count:")
    included: dict[str, bool] = {}
    for _, row in auto_games.iterrows():
        default = included_map.get(row["game_id"], True)
        label = f"{row['away_team']} @ {row['home_team']} — {row['weekday']} {row['gametime']}"
        included[row["game_id"]] = st.checkbox(
            label, value=default, key=f"include_{season}_{week}_{row['game_id']}"
        )

    if st.button("Regenerate picks"):
        games_all = pc.games_with_included_flags(auto_games, included)
        chosen = games_all[games_all["included"]]
        ranked, pending = pc.rank_games(chosen)
        if not pending.empty:
            missing = ", ".join(
                f"{r['away_team']} @ {r['home_team']}" for _, r in pending.iterrows()
            )
            st.warning(f"Odds not posted yet for: {missing} — try again closer to kickoff.")
        store.save_week(conn, season, week, games_all, ranked, datetime.now(pc.ET))
        st.rerun()
    elif not saved_picks.empty:
        st.caption(f"Last generated: {status['generated_at']}")
        _render_picks_table(saved_games, saved_picks)
    else:
        st.info("No picks generated yet for this week — click Regenerate picks.")


def _render_picks_table(games: pd.DataFrame, picks: pd.DataFrame) -> None:
    merged = picks.merge(games[["game_id", "home_team", "away_team"]], on="game_id", how="left")
    display = merged[["points", "predicted_winner", "away_team", "home_team", "confidence"]].copy()
    display["confidence"] = (display["confidence"].abs() * 100).round(1).astype(str) + "%"
    display.columns = ["Points", "Pick", "Away", "Home", "Confidence"]
    st.dataframe(display, hide_index=True, width="stretch")
