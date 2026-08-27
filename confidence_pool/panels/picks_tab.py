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
        _render_week_score(conn, season, week, saved_picks, team_names, status)
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
        "future comparison; doesn't affect this week's locked picks. A "
        "blank point box, an unmarked winner, or two games sharing the "
        "same points value are all real, allowed outcomes here -- the "
        "bylaws define exactly what happens (rules 15, 16, 7), so this "
        "records what actually happened rather than blocking the save."
    )

    existing = store.load_actual_picks(conn, season, week)
    existing_by_game = (
        {row["game_id"]: row for _, row in existing.iterrows()} if not existing.empty else {}
    )
    merged = algorithm_picks.merge(
        games[["game_id", "home_team", "away_team"]], on="game_id", how="left"
    )
    num_games = len(merged)
    game_labels = {
        row["game_id"]: f"{team_names.get(row['away_team'], row['away_team'])} @ "
        f"{team_names.get(row['home_team'], row['home_team'])}"
        for _, row in merged.iterrows()
    }

    existing_late = bool(existing["late"].iloc[0]) if not existing.empty else False
    if existing_by_game:
        existing_entries = {
            gid: (
                row["predicted_winner"],
                int(row["points"]) if pd.notna(row["points"]) else None,
            )
            for gid, row in existing_by_game.items()
        }
        existing_issues = pc.check_actual_picks(existing_entries, game_labels, late=existing_late)
        if existing_issues:
            st.warning(
                "This week's recorded submission has an irregularity the bylaws "
                "define a specific resolution for (not excluded):\n\n"
                + "\n".join(f"- {issue}" for issue in existing_issues)
            )

    late = st.checkbox(
        "This card was submitted late",
        value=existing_late,
        help="Bylaws rule 2: a late card isn't excluded -- it's docked 10 "
        "points below that week's lowest card.",
        key=f"actual_late_{season}_{week}",
    )

    entries: dict[str, tuple[str | None, int | None]] = {}
    for _, row in merged.iterrows():
        game_id = row["game_id"]
        home, away = row["home_team"], row["away_team"]
        default = existing_by_game.get(game_id, row)
        default_winner = default["predicted_winner"]
        default_points = default["points"]
        if pd.isna(default_points):
            default_points = None
        col_winner, col_points = st.columns(2)
        with col_winner:
            winner_options = [home, away, None]
            winner = st.selectbox(
                game_labels[game_id],
                options=winner_options,
                index=winner_options.index(default_winner) if default_winner in (home, away) else 2,
                format_func=lambda t: team_names.get(t, t) if t is not None else "(not marked)",
                key=f"actual_winner_{season}_{week}_{game_id}",
            )
        with col_points:
            points_raw = st.number_input(
                "Points (0 = leave blank)", min_value=0, max_value=num_games,
                value=int(default_points) if default_points is not None else 0,
                step=1, key=f"actual_points_{season}_{week}_{game_id}",
            )
        entries[game_id] = (winner, points_raw if points_raw > 0 else None)

    if st.button("Save actual submission"):
        actual_df = pd.DataFrame(
            [
                {"game_id": game_id, "predicted_winner": winner, "points": points}
                for game_id, (winner, points) in entries.items()
            ]
        )
        store.save_actual_picks(conn, season, week, actual_df, datetime.now(pc.ET), late=late)
        issues = pc.check_actual_picks(entries, game_labels, late=late)
        if issues:
            st.warning(
                "Saved -- but this submission has an irregularity the bylaws "
                "define a specific resolution for (not excluded):\n\n"
                + "\n".join(f"- {issue}" for issue in issues)
            )
        else:
            st.success("Actual submission saved.")
        st.rerun()
    elif not existing.empty:
        st.caption(f"Last recorded: {existing['entered_at'].iloc[0]}")


def _entries_from_picks(picks: pd.DataFrame) -> dict[str, tuple[str | None, int | None]]:
    return {
        row["game_id"]: (
            row["predicted_winner"] if pd.notna(row["predicted_winner"]) else None,
            int(row["points"]) if pd.notna(row["points"]) else None,
        )
        for _, row in picks.iterrows()
    }


def _render_week_score(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    saved_picks: pd.DataFrame,
    team_names: dict[str, str],
    status: dict | None,
) -> None:
    """A locked week's real score, once outcomes are known -- the
    algorithm's hypothetical total next to what you actually submitted, per
    `picks_core.score_picks`. Also where the pool's officially reported
    score gets recorded, since bylaws rule 2's late-card penalty needs
    every other entrant's score, which this app doesn't track -- see
    `picks_core.check_reported_score`.
    """
    outcomes = store.get_game_outcomes(conn, season, week)
    algo_score = pc.score_picks(_entries_from_picks(saved_picks), outcomes)
    if algo_score.games_decided == 0:
        st.caption("This week's games haven't finished yet -- scores will appear here once results are in.")
        return

    st.subheader("This week's result")
    partial = algo_score.games_decided < algo_score.games_total
    suffix = (
        f" ({algo_score.games_decided}/{algo_score.games_total} games decided so far)"
        if partial
        else ""
    )
    st.write(f"Algorithm score: **{algo_score.total_points}**{suffix}")

    actual = store.load_actual_picks(conn, season, week)
    late = bool(actual["late"].iloc[0]) if not actual.empty else False
    actual_score = pc.score_picks(_entries_from_picks(actual), outcomes) if not actual.empty else None
    if actual_score is not None:
        st.write(f"Your actual score: **{actual_score.total_points}**{suffix}")
        if late:
            st.caption(
                "Bylaws rule 2's late-card penalty (10 points below the field's "
                "lowest card) isn't reflected above -- this app has no visibility "
                "into other entrants' scores. Enter the commissioner's reported "
                "score below once it's posted."
            )
        with st.expander("Game-by-game breakdown"):
            rows = []
            for r in actual_score.results:
                rows.append(
                    {
                        "Your pick": team_names.get(r.predicted_winner, r.predicted_winner)
                        if r.predicted_winner
                        else "(not marked)",
                        "Points assigned": r.points if r.points is not None else "(blank)",
                        "Actual winner": team_names.get(r.actual_winner, r.actual_winner)
                        if r.actual_winner
                        else ("tied" if r.decided else "TBD"),
                        "Points awarded": r.points_awarded,
                    }
                )
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No actual submission recorded for this week yet.")

    max_score = algo_score.games_total * (algo_score.games_total + 1) // 2
    reported = status.get("reported_score") if status else None
    reported_input = st.number_input(
        "Reported score from the pool (0 = not yet entered)",
        min_value=0,
        max_value=max_score,
        value=int(reported) if reported is not None else 0,
        step=1,
        key=f"reported_score_{season}_{week}",
    )
    if st.button("Save reported score", key=f"save_reported_score_{season}_{week}"):
        store.set_reported_score(
            conn, season, week, reported_input if reported_input > 0 else None, datetime.now(pc.ET)
        )
        st.success("Reported score saved.")
        st.rerun()
    elif actual_score is not None and reported is not None:
        mismatch = pc.check_reported_score(actual_score, int(reported), late)
        if mismatch:
            st.warning(mismatch)
