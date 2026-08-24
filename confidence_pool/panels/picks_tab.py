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
    team_names = store.get_team_display_names(conn)

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

    store.sync_game_outcomes(conn, schedule, datetime.now(pc.ET))

    season_row = store.get_season(conn, season) or {}
    cutoff = season_row.get("sunday_afternoon_cutoff", pc.SUNDAY_AFTERNOON_CUTOFF)
    week_rule = store.get_week_rule(conn, season, week)
    selection_rule = week_rule["selection_rule"] if week_rule else "standard"

    auto_games = pc.select_games(schedule, season, week, selection_rule, cutoff)
    if auto_games.empty:
        st.warning(f"No games matched the pool's selection rules for week {week}.")
        return

    configured_deadline = None
    if week_rule and week_rule.get("deadline_override"):
        configured_deadline = datetime.fromisoformat(week_rule["deadline_override"])
    deadline = pc.week_deadline(auto_games, configured_deadline)

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
        outcome = pc.resolve_week_lock(auto_games, included_map, saved_games, saved_picks, now)
        if outcome.warning:
            st.warning(outcome.warning)
        if outcome.locked:
            store.save_week(
                conn, season, week, outcome.games, outcome.picks, outcome.generated_at,
                first_snapshot_eligible=pc.is_first_look_window(auto_games, outcome.generated_at),
                lock=True,
            )
            saved_games, saved_picks, status = store.load_week(conn, season, week)
            locked = True

    st.caption(f"Pick deadline: {deadline.strftime('%a %b %d, %I:%M %p ET')}")
    if week_rule:
        st.info(
            f"Week {week} uses an early, commissioner-announced cutoff instead of "
            "kickoff time (bylaws rule 2) — verify it against this season's actual "
            "league rules and adjust it in the Settings tab if it's changed."
        )

    if locked:
        st.success(f"Week {week} picks are locked (final as of {status['locked_at']}).")
        _render_picks_table(saved_games, saved_picks, team_names)
        _render_actual_picks_form(conn, season, week, saved_games, saved_picks, team_names)
        return

    st.write("Games evaluated this week — uncheck any that shouldn't count:")
    included: dict[str, bool] = {}
    for _, row in auto_games.iterrows():
        default = included_map.get(row["game_id"], True)
        away = team_names.get(row["away_team"], row["away_team"])
        home = team_names.get(row["home_team"], row["home_team"])
        label = f"{away} @ {home} — {row['weekday']} {row['gametime']}"
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
        generated_at = datetime.now(pc.ET)
        store.save_week(
            conn, season, week, games_all, ranked, generated_at,
            first_snapshot_eligible=pc.is_first_look_window(auto_games, generated_at),
        )
        st.rerun()
    elif not saved_picks.empty:
        st.caption(f"Last generated: {status['generated_at']}")
        _render_picks_table(saved_games, saved_picks, team_names)
    else:
        st.info("No picks generated yet for this week — click Regenerate picks.")


def _render_picks_table(games: pd.DataFrame, picks: pd.DataFrame, team_names: dict[str, str]) -> None:
    merged = picks.merge(games[["game_id", "home_team", "away_team"]], on="game_id", how="left")
    display = merged[["points", "predicted_winner", "away_team", "home_team", "confidence"]].copy()
    for col in ("predicted_winner", "away_team", "home_team"):
        display[col] = display[col].map(lambda t: team_names.get(t, t))
    display["confidence"] = (display["confidence"].abs() * 100).round(1).astype(str) + "%"
    display.columns = ["Points", "Pick", "Away", "Home", "Confidence"]
    st.dataframe(display, hide_index=True, width="stretch")


def _render_actual_picks_form(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    games: pd.DataFrame,
    algorithm_picks: pd.DataFrame,
    team_names: dict[str, str],
) -> None:
    """A locked week's actual-submission form -- what you really wrote on
    the pool sheet, if it differed from the recommendation, recorded so a
    future season can compare algorithm vs. actual. Defaults every field
    to the algorithm's own recommendation, edited only where it deviated.
    """
    st.subheader("Your actual submission")
    st.caption(
        "Defaults to the recommendation above -- edit only what you "
        "actually wrote on the pool sheet, then save. Purely a record for "
        "future comparison; doesn't affect this week's locked picks."
    )

    existing = store.load_actual_picks(conn, season, week)
    existing_by_game = (
        {row["game_id"]: row for _, row in existing.iterrows()} if not existing.empty else {}
    )
    merged = algorithm_picks.merge(
        games[["game_id", "home_team", "away_team"]], on="game_id", how="left"
    )
    num_games = len(merged)

    entries: dict[str, tuple[str, int]] = {}
    for _, row in merged.iterrows():
        game_id = row["game_id"]
        home, away = row["home_team"], row["away_team"]
        default = existing_by_game.get(game_id, row)
        col_winner, col_points = st.columns(2)
        with col_winner:
            winner = st.selectbox(
                f"{team_names.get(away, away)} @ {team_names.get(home, home)}",
                options=[home, away],
                index=0 if default["predicted_winner"] == home else 1,
                format_func=lambda t: team_names.get(t, t),
                key=f"actual_winner_{season}_{week}_{game_id}",
            )
        with col_points:
            points = st.number_input(
                "Points", min_value=1, max_value=num_games, value=int(default["points"]),
                step=1, key=f"actual_points_{season}_{week}_{game_id}",
            )
        entries[game_id] = (winner, points)

    if st.button("Save actual submission"):
        points_used = sorted(points for _, points in entries.values())
        if points_used != list(range(1, num_games + 1)):
            st.error(
                f"Points must use each value 1-{num_games} exactly once, with no "
                "repeats or gaps -- check for a duplicate or typo above."
            )
        else:
            actual_df = pd.DataFrame(
                [
                    {"game_id": game_id, "predicted_winner": winner, "points": points}
                    for game_id, (winner, points) in entries.items()
                ]
            )
            store.save_actual_picks(conn, season, week, actual_df, datetime.now(pc.ET))
            st.success("Actual submission saved.")
            st.rerun()
    elif not existing.empty:
        st.caption(f"Last recorded: {existing['entered_at'].iloc[0]}")
