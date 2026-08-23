"""Tests for confidence_pool.store -- SQLite persistence, in-memory only
(no real file on disk), per testing.md."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

import store


@pytest.fixture
def conn():
    return store.connect(":memory:")


def _games_df():
    return pd.DataFrame(
        [
            {
                "game_id": "g1",
                "home_team": "AAA",
                "away_team": "BBB",
                "home_moneyline": -150.0,
                "away_moneyline": 130.0,
                "gameday": "2026-09-13",
                "weekday": "Sunday",
                "gametime": "13:00",
                "included": True,
            }
        ]
    )


def _picks_df():
    return pd.DataFrame(
        [{"game_id": "g1", "points": 1, "predicted_winner": "AAA", "confidence": 0.2}]
    )


class TestSeasonConfig:
    def test_no_active_season_by_default(self, conn):
        assert store.get_active_season(conn) is None

    def test_set_active_season_marks_it_active(self, conn):
        store.set_active_season(conn, 2026)

        assert store.get_active_season(conn) == 2026

    def test_setting_a_new_active_season_clears_the_old_one(self, conn):
        store.set_active_season(conn, 2026)
        store.set_active_season(conn, 2027)

        assert store.get_active_season(conn) == 2027

    def test_late_season_deadline_rejects_weeks_outside_17_18(self, conn):
        with pytest.raises(ValueError):
            store.set_late_season_deadline(conn, 2026, 16, datetime(2026, 12, 20))

    def test_late_season_deadline_round_trips_per_week(self, conn):
        w17 = datetime(2026, 12, 26, 13, 0)
        w18 = datetime(2027, 1, 2, 16, 30)

        store.set_late_season_deadline(conn, 2026, 17, w17)
        store.set_late_season_deadline(conn, 2026, 18, w18)

        config = store.get_season_config(conn, 2026)
        assert config["week17_deadline"] == w17.isoformat()
        assert config["week18_deadline"] == w18.isoformat()


class TestTeamDisplayNames:
    """Pool-sheet display-name overrides for nfl_data_py's team abbreviations."""

    def test_connect_seeds_the_known_defaults(self, conn):
        names = store.get_team_display_names(conn)

        assert names["LAC"] == "LA Chargers"
        assert names["LA"] == "LA Rams"
        assert len(names) == 32

    def test_set_team_display_name_overrides_the_seeded_default(self, conn):
        store.set_team_display_name(conn, "SEA", "Seahawks")

        assert store.get_team_display_names(conn)["SEA"] == "Seahawks"

    def test_reseeding_does_not_clobber_a_prior_edit(self, conn):
        store.set_team_display_name(conn, "SEA", "Seahawks")

        store._seed_default_team_display_names(conn)  # simulates a later app restart

        assert store.get_team_display_names(conn)["SEA"] == "Seahawks"


class TestSaveAndLoadWeek:
    def test_round_trips_games_and_picks(self, conn):
        store.save_week(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 10, 9, 0))

        games, picks, status = store.load_week(conn, 2026, 1)

        assert len(games) == 1
        assert games.loc[0, "home_team"] == "AAA"
        assert len(picks) == 1
        assert picks.loc[0, "points"] == 1
        assert status["locked"] == 0

    def test_loading_an_unsaved_week_returns_empty_frames_and_no_status(self, conn):
        games, picks, status = store.load_week(conn, 2026, 5)

        assert games.empty
        assert picks.empty
        assert status is None

    def test_regenerating_before_lock_overwrites_the_prior_snapshot(self, conn):
        store.save_week(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 10, 9, 0))

        updated_picks = _picks_df()
        updated_picks.loc[0, "confidence"] = 0.9
        store.save_week(conn, 2026, 1, _games_df(), updated_picks, datetime(2026, 9, 10, 10, 0))

        _, picks, _ = store.load_week(conn, 2026, 1)
        assert picks.loc[0, "confidence"] == pytest.approx(0.9)

    def test_locking_a_week_prevents_further_overwrites(self, conn):
        store.save_week(
            conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 13, 13, 0), lock=True
        )

        with pytest.raises(ValueError):
            store.save_week(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 13, 14, 0))

    def test_locking_records_locked_at(self, conn):
        store.save_week(
            conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 13, 13, 0), lock=True
        )

        status = store.get_week_status(conn, 2026, 1)
        assert status["locked"] == 1
        assert status["locked_at"] == "2026-09-13T13:00:00"
