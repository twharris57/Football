"""Picks tab: game review, ranking, deadline lock, actual submission, and scoring."""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

import picks_core as pc
import store


@st.cache_data(ttl="15m", show_spinner="Fetching schedule...")
def _cached_schedule(year: int) -> pd.DataFrame:
    return pc.get_schedule(year)


def render_picks_tab(conn: sqlite3.Connection, active_season: int, today: date) -> None:
    team_names = store.get_team_display_names(conn)

    with st.expander("How picks are ranked", expanded=False):
        st.markdown(
            (
                '1. **Moneyline → probability.** `-150` → 150/250 = 60%; `+130` → 100/230 = '
                '43.5%.\n2. **Remove the vig.** Scale both sides so they sum to 100%.\n3. '
                '**Confidence** = home − away probability. The sign picks the winner; the '
                'size is how lopsided the game is.\n4. **Points.** Most lopsided gets N '
                'points, then N-1, down to 1.\n\nExpand "Show the math" below for each '
                "game's numbers."
            )
        )

    season, week, schedule = _select_season_and_week(conn, active_season, today)

    store.sync_game_outcomes(conn, schedule, datetime.now(pc.ET))

    season_row = store.get_season(conn, season) or {}
    cutoff = season_row.get("sunday_afternoon_cutoff", pc.SUNDAY_AFTERNOON_CUTOFF)
    week_rule = store.get_week_rule(conn, season, week)
    selection_rule = week_rule["selection_rule"] if week_rule else "standard"
    configured_deadline = None
    if week_rule and week_rule.get("deadline_override"):
        configured_deadline = datetime.fromisoformat(week_rule["deadline_override"])

    auto_games = pc.select_games(schedule, season, week, selection_rule, cutoff, configured_deadline)
    if auto_games.empty:
        st.warning(f"No games matched the pool's selection rules for week {week}.")
        return

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
        outcome = pc.resolve_week_lock(auto_games, included_map, saved_games, saved_picks, now)
        if outcome.locked:
            store.save_week(
                conn, season, week, outcome.games, outcome.picks, outcome.generated_at,
                first_snapshot_eligible=outcome.first_snapshot_eligible,
                lock=True,
                lock_warning=outcome.warning,
            )
            saved_games, saved_picks, status = store.load_week(conn, season, week)
            locked = True
        elif outcome.warning:
            st.warning(outcome.warning)

    _render_deadline(deadline, now, is_override=configured_deadline is not None)
    if week_rule:
        st.info(
            f"Week {week} uses the commissioner's early cutoff, not kickoff time (rule 2). "
            "Verify it in Settings."
        )

    if locked:
        _render_locked_week(conn, season, week, saved_games, saved_picks, status, team_names)
    else:
        _render_open_week(conn, season, week, auto_games, included_map, saved_games, saved_picks, status, team_names)


def _load_schedule(year: int) -> pd.DataFrame:
    """The season's schedule, or an error and stop if nfl_data_py can't be reached."""
    try:
        return _cached_schedule(year)
    except OSError as exc:
        st.error(f"Couldn't fetch the schedule from nfl_data_py: {exc}. Try reloading the page.")
        st.stop()


def _select_season_and_week(
    conn: sqlite3.Connection, active_season: int, today: date
) -> tuple[int, int, pd.DataFrame]:
    """Season and week pickers; returns `(season, week, schedule)`."""
    season_options = sorted(set(store.known_seasons(conn)) | {active_season})
    col_season, col_week = st.columns(2)
    with col_season:
        season = st.selectbox(
            "Season", options=season_options, index=season_options.index(active_season)
        )
    schedule = _load_schedule(season)

    default_week = pc.current_week(schedule, today)
    week_labels = pc.week_date_labels(schedule)
    week_options = sorted(week_labels) or [default_week]
    with col_week:
        week = st.selectbox(
            "Week",
            options=week_options,
            index=week_options.index(default_week) if default_week in week_options else 0,
            format_func=lambda w: f"Week {w} ({week_labels[w]})" if w in week_labels else f"Week {w}",
        )
    return season, week, schedule


def _render_locked_week(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    saved_games: pd.DataFrame,
    saved_picks: pd.DataFrame,
    status: dict,
    team_names: dict[str, str],
) -> None:
    st.success(f"Week {week} picks are locked (final as of {status['locked_at']}).")
    if status.get("lock_warning"):
        st.warning(status["lock_warning"])
    display_games, display_picks = _render_snapshot_selector(
        conn, season, week, "locked", saved_games, saved_picks
    )
    _render_picks_table(display_games, display_picks, team_names)
    _render_pick_details(display_games, display_picks, team_names)
    _render_actual_picks_form(conn, season, week, saved_games, saved_picks, team_names)
    _render_week_score(conn, season, week, saved_picks, team_names, status)


def _render_open_week(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    auto_games: pd.DataFrame,
    included_map: dict[str, bool],
    saved_games: pd.DataFrame,
    saved_picks: pd.DataFrame,
    status: dict | None,
    team_names: dict[str, str],
) -> None:
    included: dict[str, bool] = {}
    with st.expander("Games evaluated this week — uncheck any that shouldn't count", expanded=False):
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
        display_games, display_picks = _render_snapshot_selector(
            conn, season, week, "unlocked", saved_games, saved_picks
        )
        _render_picks_table(display_games, display_picks, team_names)
        _render_pick_details(display_games, display_picks, team_names)
    else:
        st.info("No picks generated yet for this week — click Regenerate picks.")


def _render_deadline(deadline: datetime, now: datetime, is_override: bool) -> None:
    """Show the deadline, escalating to warning within 24h (or for an early cutoff) and error once passed."""
    deadline_str = deadline.strftime("%a %b %d, %I:%M %p ET")
    remaining = deadline - now
    if is_override:
        st.badge("Early cutoff — not the usual kickoff-based deadline", color="orange")
    if remaining <= timedelta(0):
        st.error(f"**Pick deadline has passed:** {deadline_str}")
    elif remaining <= timedelta(hours=24) or is_override:
        suffix = f" — {_format_remaining(remaining)} left" if remaining <= timedelta(hours=24) else ""
        st.warning(f"**Pick deadline: {deadline_str}**{suffix}")
    else:
        st.info(f"**Pick deadline: {deadline_str}**")


def _format_remaining(remaining: timedelta) -> str:
    total_minutes = max(int(remaining.total_seconds() // 60), 0)
    hours, minutes = divmod(total_minutes, 60)
    if hours >= 1:
        return f"about {hours}h {minutes}m"
    return f"about {minutes}m"


def _full_table_height(num_rows: int) -> int:
    """Height (px) that shows every row without an inner scrollbar."""
    return 35 * (num_rows + 1) + 3


def _render_snapshot_selector(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    key_suffix: str,
    current_games: pd.DataFrame,
    current_picks: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Toggle between the week's `'first'` and `'current'` snapshots, once a `'first'` exists."""
    first_games, first_picks, _ = store.load_week(conn, season, week, snapshot_type="first")
    if first_games.empty:
        return current_games, current_picks
    choice = st.radio(
        "Snapshot",
        options=["Current", "First look"],
        horizontal=True,
        key=f"snapshot_{key_suffix}_{season}_{week}",
    )
    if choice == "First look":
        return first_games, first_picks
    return current_games, current_picks


def _render_picks_table(games: pd.DataFrame, picks: pd.DataFrame, team_names: dict[str, str]) -> None:
    merged = picks.merge(games[["game_id", "home_team", "away_team"]], on="game_id", how="left")
    display = merged[["points", "predicted_winner", "away_team", "home_team", "confidence"]].copy()
    for col in ("predicted_winner", "away_team", "home_team"):
        display[col] = display[col].map(lambda t: team_names.get(t, t))
    display["confidence"] = (display["confidence"].abs() * 100).round(1).astype(str) + "%"
    display.columns = ["Points", "Pick", "Away", "Home", "Confidence"]
    st.dataframe(
        display, hide_index=True, width="stretch", height=_full_table_height(len(display))
    )


def _render_pick_details(games: pd.DataFrame, picks: pd.DataFrame, team_names: dict[str, str]) -> None:
    """Per-pick expander showing moneylines and de-vig math."""
    merged = picks.merge(
        games[["game_id", "home_team", "away_team", "home_moneyline", "away_moneyline"]],
        on="game_id",
        how="left",
    ).sort_values("points", ascending=False)
    with st.expander("Show the math for each pick"):
        for _, row in merged.iterrows():
            away = team_names.get(row["away_team"], row["away_team"])
            home = team_names.get(row["home_team"], row["home_team"])
            pick = team_names.get(row["predicted_winner"], row["predicted_winner"])
            st.markdown(f"**{row['points']} pts — {away} @ {home}** (picked: {pick})")
            explanation = pc.explain_odds(row["home_moneyline"], row["away_moneyline"])
            detail = pd.DataFrame(
                [
                    {
                        "": "Moneyline",
                        home: f"{explanation.home_moneyline:+.0f}",
                        away: f"{explanation.away_moneyline:+.0f}",
                    },
                    {
                        "": "Raw implied probability",
                        home: f"{explanation.home_prob_raw:.1%}",
                        away: f"{explanation.away_prob_raw:.1%}",
                    },
                    {
                        "": "After vig removal",
                        home: f"{explanation.home_prob:.1%}",
                        away: f"{explanation.away_prob:.1%}",
                    },
                ]
            )
            st.dataframe(
                detail, hide_index=True, width="stretch", height=_full_table_height(len(detail))
            )
            st.caption(f"Confidence = {explanation.home_prob:.1%} − {explanation.away_prob:.1%} = {explanation.confidence:+.1%}")


def _render_actual_picks_form(
    conn: sqlite3.Connection,
    season: int,
    week: int,
    games: pd.DataFrame,
    algorithm_picks: pd.DataFrame,
    team_names: dict[str, str],
) -> None:
    """Form recording the card actually submitted, defaulting to the algorithm's picks."""
    st.subheader("Your actual submission")
    st.caption(
        (
            'Defaults to the recommendation. Edit only what you actually wrote, then '
            "save; this is a record and doesn't change the locked picks. Blank points, "
            'unmarked winners, and duplicate points are allowed; the bylaws resolve '
            'them (rules 15, 16, 7).'
        )
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
        help="Rule 2: a late card scores 10 points below that week's lowest card.",
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
    """Algorithm vs. actual score once outcomes exist, plus the reported-score entry."""
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
                (
                    "The late-card penalty (rule 2) depends on other entrants' scores, so it "
                    "isn't included. Enter the commissioner's reported score below."
                )
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
            breakdown = pd.DataFrame(rows)
            st.dataframe(
                breakdown, hide_index=True, width="stretch",
                height=_full_table_height(len(breakdown)),
            )
    else:
        st.caption("No actual submission recorded for this week yet.")

    max_score = algo_score.games_total * (algo_score.games_total + 1) // 2
    # A late card scores 10 below the field's lowest (rule 2); on-time cards can't go below 0.
    min_score = -10
    reported = status.get("reported_score") if status else None
    col_score, col_clear = st.columns([4, 1])
    with col_score:
        reported_input = st.number_input(
            "Reported score from the pool",
            min_value=min_score,
            max_value=max_score,
            value=int(reported) if reported is not None else 0,
            step=1,
            key=f"reported_score_{season}_{week}",
        )
    with col_clear:
        st.write("")
        clear_clicked = st.button(
            "Clear", key=f"clear_reported_score_{season}_{week}", disabled=reported is None
        )
    save_clicked = st.button("Save reported score", key=f"save_reported_score_{season}_{week}")

    if clear_clicked:
        store.set_reported_score(conn, season, week, None, datetime.now(pc.ET))
        st.success("Reported score cleared.")
        st.rerun()
    elif save_clicked:
        store.set_reported_score(conn, season, week, reported_input, datetime.now(pc.ET))
        st.success("Reported score saved.")
        st.rerun()
    elif actual_score is not None and reported is not None:
        mismatch = pc.check_reported_score(actual_score, int(reported), late)
        if mismatch:
            st.warning(mismatch)
