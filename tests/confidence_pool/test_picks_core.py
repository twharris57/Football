"""Tests for confidence_pool.picks_core -- all against synthetic schedule
DataFrames, no real nfl_data_py calls (per testing.md)."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

import picks_core as pc


def _game(
    game_id,
    week,
    weekday,
    gametime,
    gameday="2026-09-13",
    home_team="AAA",
    away_team="BBB",
    home_moneyline=-150.0,
    away_moneyline=130.0,
    game_type="REG",
    season=2026,
):
    return {
        "game_id": game_id,
        "season": season,
        "game_type": game_type,
        "week": week,
        "gameday": gameday,
        "weekday": weekday,
        "gametime": gametime,
        "home_team": home_team,
        "away_team": away_team,
        "home_moneyline": home_moneyline,
        "away_moneyline": away_moneyline,
    }


class TestComputeProbability:
    """American-odds -> implied win probability, before any normalization."""

    def test_favorite_negative_moneyline(self):
        assert pc.compute_probability(-150) == pytest.approx(150 / 250)

    def test_underdog_positive_moneyline(self):
        assert pc.compute_probability(130) == pytest.approx(100 / 230)


class TestSelectGames:
    """The Legion pool's game-selection rules (bylaws rule 14)."""

    def test_keeps_sunday_afternoon_and_monday_night_for_early_weeks(self):
        schedule = pd.DataFrame(
            [
                _game("g1", 1, "Sunday", "13:00"),
                _game("g2", 1, "Monday", "20:15"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 1)

        assert set(selected["game_id"]) == {"g1", "g2"}

    def test_excludes_thursday_and_early_sunday_games(self):
        schedule = pd.DataFrame(
            [
                _game("thu", 1, "Thursday", "20:20"),
                _game("early_sun", 1, "Sunday", "09:30"),
                _game("kept", 1, "Sunday", "13:00"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 1)

        assert set(selected["game_id"]) == {"kept"}

    def test_excludes_non_regular_season_game_types(self):
        schedule = pd.DataFrame(
            [
                _game("reg", 1, "Sunday", "13:00", game_type="REG"),
                _game("playoff", 1, "Sunday", "13:00", game_type="WC"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 1)

        assert set(selected["game_id"]) == {"reg"}

    def test_weeks_17_and_18_keep_only_saturday_games(self):
        schedule = pd.DataFrame(
            [
                _game("sat", 17, "Saturday", "16:30"),
                _game("sun", 17, "Sunday", "13:00"),
                _game("mon", 17, "Monday", "20:15"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 17)

        assert set(selected["game_id"]) == {"sat"}


class TestRankGames:
    """Confidence-based N..1 point assignment, and the NaN-odds guard."""

    def test_assigns_points_descending_by_absolute_confidence(self):
        games = pd.DataFrame(
            [
                _game("landslide", 1, "Sunday", "13:00", home_moneyline=-500, away_moneyline=380),
                _game("close", 1, "Sunday", "13:00", home_moneyline=-110, away_moneyline=-110),
            ]
        )

        ranked, pending = pc.rank_games(games)

        assert pending.empty
        assert list(ranked["game_id"]) == ["landslide", "close"]
        assert list(ranked["points"]) == [2, 1]

    def test_predicted_winner_is_the_higher_probability_team(self):
        games = pd.DataFrame(
            [_game("g1", 1, "Sunday", "13:00", home_team="HOME", away_team="AWAY", home_moneyline=-500, away_moneyline=380)]
        )

        ranked, _ = pc.rank_games(games)

        assert ranked.loc[0, "predicted_winner"] == "HOME"

    def test_games_missing_odds_are_returned_as_pending_not_ranked(self):
        games = pd.DataFrame(
            [
                _game("has_odds", 1, "Sunday", "13:00"),
                _game("no_odds", 1, "Sunday", "13:00", home_moneyline=None, away_moneyline=None),
            ]
        )

        ranked, pending = pc.rank_games(games)

        assert list(ranked["game_id"]) == ["has_odds"]
        assert list(pending["game_id"]) == ["no_odds"]


class TestCurrentWeek:
    """Auto-detecting "this week" from schedule dates relative to today."""

    def test_returns_earliest_week_not_yet_fully_played(self):
        schedule = pd.DataFrame(
            [
                _game("g1", 1, "Sunday", "13:00", gameday="2026-09-13"),
                _game("g2", 2, "Sunday", "13:00", gameday="2026-09-20"),
            ]
        )

        assert pc.current_week(schedule, date(2026, 9, 15)) == 2

    def test_falls_back_to_final_week_once_season_is_over(self):
        schedule = pd.DataFrame(
            [
                _game("g1", 1, "Sunday", "13:00", gameday="2026-09-13"),
                _game("g2", 2, "Sunday", "13:00", gameday="2026-09-20"),
            ]
        )

        assert pc.current_week(schedule, date(2027, 1, 1)) == 2


class TestWeekDeadline:
    """The pick-submission cutoff -- earliest kickoff for weeks 1-16, a
    configured override for weeks 17-18 (bylaws rule 2/14)."""

    def test_early_week_deadline_is_earliest_kickoff(self):
        games = pd.DataFrame(
            [
                _game("g1", 1, "Sunday", "16:25", gameday="2026-09-13"),
                _game("g2", 1, "Sunday", "13:00", gameday="2026-09-13"),
            ]
        )

        deadline = pc.week_deadline(games, 1, configured_deadline=None)

        assert deadline == pc.kickoff_datetime("2026-09-13", "13:00")

    def test_late_season_week_uses_configured_deadline_when_present(self):
        games = pd.DataFrame([_game("g1", 17, "Saturday", "16:30", gameday="2026-12-26")])
        configured = datetime(2026, 12, 26, 13, 0, tzinfo=pc.ET)

        deadline = pc.week_deadline(games, 17, configured_deadline=configured)

        assert deadline == configured

    def test_late_season_week_falls_back_to_earliest_kickoff_when_unconfigured(self):
        games = pd.DataFrame([_game("g1", 17, "Saturday", "16:30", gameday="2026-12-26")])

        deadline = pc.week_deadline(games, 17, configured_deadline=None)

        assert deadline == pc.kickoff_datetime("2026-12-26", "16:30")


class TestIsLocked:
    def test_before_deadline_is_not_locked(self):
        deadline = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)
        now = datetime(2026, 9, 13, 12, 59, tzinfo=pc.ET)

        assert pc.is_locked(now, deadline) is False

    def test_at_or_after_deadline_is_locked(self):
        deadline = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)
        now = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)

        assert pc.is_locked(now, deadline) is True
