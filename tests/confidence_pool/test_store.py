"""Tests for confidence_pool.store -- SQLite persistence, in-memory only
(no real file on disk), per testing.md."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

import store

TEST_ALGORITHM_VERSION = "test-v1"


@pytest.fixture
def conn():
    c = store.connect(":memory:")
    # weekly_picks.algorithm_version FKs to algorithm_versions -- register one
    # so save_week() fixtures below satisfy the constraint, same as the real
    # app does once at startup (see streamlit_app.py).
    store.register_algorithm_version(c, TEST_ALGORITHM_VERSION, "test algorithm")
    return c


def _games_df(game_id="g1", home_team="KC", away_team="BUF", **overrides):
    row = {
        "game_id": game_id,
        "home_team": home_team,
        "away_team": away_team,
        "home_moneyline": -150.0,
        "away_moneyline": 130.0,
        "gameday": "2026-09-13",
        "weekday": "Sunday",
        "gametime": "13:00",
        "included": True,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _picks_df(game_id="g1", predicted_winner="KC", **overrides):
    row = {
        "game_id": game_id,
        "points": 1,
        "predicted_winner": predicted_winner,
        "confidence": 0.2,
        "algorithm_version": TEST_ALGORITHM_VERSION,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _save(conn, season_year, week, games, picks, generated_at, first_snapshot_eligible=True, **kwargs):
    """save_week() wrapper defaulting first_snapshot_eligible=True -- most
    tests here aren't exercising the first-look-window gate (see
    TestFirstSnapshotWindow), so this keeps them focused on what they
    actually test."""
    store.save_week(conn, season_year, week, games, picks, generated_at, first_snapshot_eligible, **kwargs)


class TestSeasons:
    def test_no_active_season_by_default(self, conn):
        assert store.get_active_season(conn) is None

    def test_set_active_season_marks_it_active(self, conn):
        store.set_active_season(conn, 2026)

        assert store.get_active_season(conn) == 2026

    def test_setting_a_new_active_season_clears_the_old_one(self, conn):
        store.set_active_season(conn, 2026)
        store.set_active_season(conn, 2027)

        assert store.get_active_season(conn) == 2027

    def test_unconfigured_season_has_no_row(self, conn):
        assert store.get_season(conn, 2026) is None

    def test_set_active_season_creates_a_row_with_the_default_cutoff(self, conn):
        store.set_active_season(conn, 2026)

        season = store.get_season(conn, 2026)
        assert season["sunday_afternoon_cutoff"] == "13:00"


class TestWeekRules:
    def test_unconfigured_week_has_no_rule(self, conn):
        assert store.get_week_rule(conn, 2026, 5) is None

    def test_unconfigured_weeks_17_and_18_default_to_all_games(self, conn):
        # CP-24: the "every game counts" half of the weeks-17/18 exception
        # must apply even before a human ever visits Settings -- only the
        # deadline *value* genuinely needs yearly configuration.
        for week in (17, 18):
            rule = store.get_week_rule(conn, 2026, week)
            assert rule["selection_rule"] == "all_games"
            assert rule["deadline_override"] is None

    def test_a_real_configured_week_17_18_row_overrides_the_default(self, conn):
        store.set_late_season_deadline(conn, 2026, 17, datetime(2026, 12, 26, 13, 0))

        rule = store.get_week_rule(conn, 2026, 17)
        assert rule["deadline_override"] == datetime(2026, 12, 26, 13, 0).isoformat()

    def test_late_season_deadline_rejects_weeks_outside_17_18(self, conn):
        with pytest.raises(ValueError):
            store.set_late_season_deadline(conn, 2026, 16, datetime(2026, 12, 20))

    def test_late_season_deadline_round_trips_per_week(self, conn):
        w17 = datetime(2026, 12, 26, 13, 0)
        w18 = datetime(2027, 1, 2, 16, 30)

        store.set_late_season_deadline(conn, 2026, 17, w17)
        store.set_late_season_deadline(conn, 2026, 18, w18)

        assert store.get_week_rule(conn, 2026, 17)["deadline_override"] == w17.isoformat()
        assert store.get_week_rule(conn, 2026, 18)["deadline_override"] == w18.isoformat()

    def test_late_season_deadline_sets_the_all_games_selection_rule(self, conn):
        store.set_late_season_deadline(conn, 2026, 17, datetime(2026, 12, 26, 13, 0))

        assert store.get_week_rule(conn, 2026, 17)["selection_rule"] == "all_games"

    def test_late_season_deadline_works_before_the_season_row_exists(self, conn):
        # season_week_rules.season_year FKs to seasons -- setting a deadline
        # shouldn't require the user to have visited "Set as active season" first.
        store.set_late_season_deadline(conn, 2026, 17, datetime(2026, 12, 26, 13, 0))

        assert store.get_season(conn, 2026) is not None


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

        store._seed_default_teams(conn)  # simulates a later app restart

        assert store.get_team_display_names(conn)["SEA"] == "Seahawks"


class TestAlgorithmVersions:
    def test_registering_the_same_version_twice_is_a_no_op(self, conn):
        store.register_algorithm_version(conn, TEST_ALGORITHM_VERSION, "changed description")

        # Doesn't raise, and doesn't overwrite the original description.
        row = conn.execute(
            "SELECT description FROM algorithm_versions WHERE version_id = ?",
            (TEST_ALGORITHM_VERSION,),
        ).fetchone()
        assert row["description"] == "test algorithm"


class TestSaveAndLoadWeek:
    def test_round_trips_games_and_picks(self, conn):
        _save(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 10, 9, 0))

        games, picks, status = store.load_week(conn, 2026, 1)

        assert len(games) == 1
        assert games.loc[0, "home_team"] == "KC"
        assert len(picks) == 1
        assert picks.loc[0, "points"] == 1
        assert picks.loc[0, "algorithm_version"] == TEST_ALGORITHM_VERSION
        assert status["locked"] == 0

    def test_loading_an_unsaved_week_returns_empty_frames_and_no_status(self, conn):
        games, picks, status = store.load_week(conn, 2026, 5)

        assert games.empty
        assert picks.empty
        assert status is None

    def test_regenerating_before_lock_overwrites_the_current_snapshot(self, conn):
        _save(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 10, 9, 0))

        updated_picks = _picks_df(confidence=0.9)
        _save(conn, 2026, 1, _games_df(), updated_picks, datetime(2026, 9, 10, 10, 0))

        _, picks, _ = store.load_week(conn, 2026, 1)
        assert picks.loc[0, "confidence"] == pytest.approx(0.9)

    def test_locking_a_week_prevents_further_overwrites(self, conn):
        _save(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 13, 13, 0), lock=True)

        with pytest.raises(ValueError):
            _save(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 13, 14, 0))

    def test_locking_records_locked_at(self, conn):
        _save(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 13, 13, 0), lock=True)

        status = store.get_week_status(conn, 2026, 1)
        assert status["locked"] == 1
        assert status["locked_at"] == "2026-09-13T13:00:00"

    def test_first_save_captures_an_immutable_first_snapshot(self, conn):
        _save(conn, 2026, 1, _games_df(), _picks_df(confidence=0.2), datetime(2026, 9, 10, 9, 0))
        _save(conn, 2026, 1, _games_df(), _picks_df(confidence=0.9), datetime(2026, 9, 12, 9, 0))

        first = conn.execute(
            "SELECT confidence FROM weekly_picks WHERE game_id = 'g1' AND snapshot_type = 'first'"
        ).fetchone()
        current = conn.execute(
            "SELECT confidence FROM weekly_picks WHERE game_id = 'g1' AND snapshot_type = 'current'"
        ).fetchone()

        assert first["confidence"] == pytest.approx(0.2)  # untouched by the later regenerate
        assert current["confidence"] == pytest.approx(0.9)

    def test_saving_stores_the_stable_game_facts_in_games(self, conn):
        _save(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 10, 9, 0))

        game = conn.execute("SELECT * FROM games WHERE game_id = 'g1'").fetchone()
        assert game["season_year"] == 2026
        assert game["week"] == 1


class TestFirstSnapshotEligibility:
    """A save made while previewing a future week (first_snapshot_eligible=False,
    from picks_core.is_first_look_window()) must not get permanently recorded
    as that week's 'first' look -- only the first *eligible* save can."""

    def test_an_ineligible_save_does_not_capture_a_first_snapshot(self, conn):
        store.save_week(
            conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 1, 9, 0),
            first_snapshot_eligible=False,
        )

        first = conn.execute(
            "SELECT 1 FROM weekly_games WHERE game_id = 'g1' AND snapshot_type = 'first'"
        ).fetchone()
        assert first is None
        # 'current' still saves normally -- previewing a future week still works.
        current = conn.execute(
            "SELECT 1 FROM weekly_games WHERE game_id = 'g1' AND snapshot_type = 'current'"
        ).fetchone()
        assert current is not None

    def test_the_first_eligible_save_becomes_first_even_if_later_saves_preceded_it(self, conn):
        store.save_week(  # an early preview, weeks before kickoff
            conn, 2026, 1, _games_df(), _picks_df(confidence=0.1), datetime(2026, 9, 1, 9, 0),
            first_snapshot_eligible=False,
        )
        store.save_week(  # the real first look, a few days before kickoff
            conn, 2026, 1, _games_df(), _picks_df(confidence=0.2), datetime(2026, 9, 10, 9, 0),
            first_snapshot_eligible=True,
        )

        first = conn.execute(
            "SELECT confidence FROM weekly_picks WHERE game_id = 'g1' AND snapshot_type = 'first'"
        ).fetchone()
        assert first["confidence"] == pytest.approx(0.2)  # not the 0.1 preview

    def test_an_eligible_save_after_first_is_already_captured_does_not_overwrite_it(self, conn):
        store.save_week(
            conn, 2026, 1, _games_df(), _picks_df(confidence=0.2), datetime(2026, 9, 10, 9, 0),
            first_snapshot_eligible=True,
        )
        store.save_week(
            conn, 2026, 1, _games_df(), _picks_df(confidence=0.9), datetime(2026, 9, 12, 9, 0),
            first_snapshot_eligible=True,
        )

        first = conn.execute(
            "SELECT confidence FROM weekly_picks WHERE game_id = 'g1' AND snapshot_type = 'first'"
        ).fetchone()
        assert first["confidence"] == pytest.approx(0.2)


class TestSyncGameOutcomes:
    def test_backfills_scores_for_an_already_known_game(self, conn):
        _save(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 10, 9, 0))
        schedule = pd.DataFrame(
            [{"game_id": "g1", "home_score": 27.0, "away_score": 20.0}]
        )

        store.sync_game_outcomes(conn, schedule, datetime(2026, 9, 14, 12, 0))

        game = conn.execute("SELECT * FROM games WHERE game_id = 'g1'").fetchone()
        assert game["home_score"] == 27.0
        assert game["away_score"] == 20.0
        assert game["outcome_synced_at"] is not None

    def test_does_not_insert_a_game_the_app_never_evaluated(self, conn):
        schedule = pd.DataFrame(
            [{"game_id": "never_saved", "home_score": 10.0, "away_score": 7.0}]
        )

        store.sync_game_outcomes(conn, schedule, datetime(2026, 9, 14, 12, 0))

        assert conn.execute("SELECT * FROM games WHERE game_id = 'never_saved'").fetchone() is None

    def test_ignores_games_with_no_score_yet(self, conn):
        _save(conn, 2026, 1, _games_df(), _picks_df(), datetime(2026, 9, 10, 9, 0))
        schedule = pd.DataFrame(
            [{"game_id": "g1", "home_score": None, "away_score": None}]
        )

        store.sync_game_outcomes(conn, schedule, datetime(2026, 9, 14, 12, 0))

        game = conn.execute("SELECT * FROM games WHERE game_id = 'g1'").fetchone()
        assert game["home_score"] is None
