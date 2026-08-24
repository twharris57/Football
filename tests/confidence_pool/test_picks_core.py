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

    def test_all_games_rule_takes_every_game_with_no_weekday_filter(self):
        # 'all_games' (from store.season_week_rules -- weeks 17-18 today,
        # but driven by data, not hardcoded here) isn't a narrower
        # game-selection special case -- real 2025-season results (scores
        # up to 114, only possible with ~15 games on the sheet) and the
        # actual week-18 sheet (Saturday Jan 3 + Sunday Jan 4 both listed)
        # confirmed every game counts, unlike 'standard's Sunday-afternoon/
        # Monday-only filter.
        schedule = pd.DataFrame(
            [
                _game("sat", 17, "Saturday", "16:30"),
                _game("sun_early", 17, "Sunday", "09:30"),
                _game("sun_afternoon", 17, "Sunday", "13:00"),
                _game("mon", 17, "Monday", "20:15"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 17, selection_rule="all_games")

        assert set(selected["game_id"]) == {"sat", "sun_early", "sun_afternoon", "mon"}

    def test_standard_rule_is_the_default(self):
        schedule = pd.DataFrame(
            [
                _game("sat", 17, "Saturday", "16:30"),
                _game("sun_afternoon", 17, "Sunday", "13:00"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 17)

        assert set(selected["game_id"]) == {"sun_afternoon"}

    def test_sunday_afternoon_cutoff_is_configurable(self):
        schedule = pd.DataFrame([_game("early", 1, "Sunday", "12:00")])

        assert pc.select_games(schedule, 2026, 1).empty
        assert not pc.select_games(schedule, 2026, 1, sunday_afternoon_cutoff="12:00").empty


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

    def test_ranked_picks_carry_the_current_algorithm_version(self):
        games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00")])

        ranked, _ = pc.rank_games(games)

        assert ranked.loc[0, "algorithm_version"] == pc.ALGORITHM_VERSION


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
    """The pick-submission cutoff -- earliest kickoff by default, or an
    explicit override supplied by the caller (from `store.season_week_rules`,
    e.g. for weeks 17-18 -- bylaws rule 2/14). `week_deadline()` itself just
    trusts whichever the caller passes; it doesn't know which weeks are special."""

    def test_deadline_is_earliest_kickoff_when_unconfigured(self):
        games = pd.DataFrame(
            [
                _game("g1", 1, "Sunday", "16:25", gameday="2026-09-13"),
                _game("g2", 1, "Sunday", "13:00", gameday="2026-09-13"),
            ]
        )

        deadline = pc.week_deadline(games, configured_deadline=None)

        assert deadline == pc.kickoff_datetime("2026-09-13", "13:00")

    def test_configured_deadline_overrides_earliest_kickoff(self):
        games = pd.DataFrame([_game("g1", 17, "Sunday", "13:00", gameday="2026-12-27")])
        configured = datetime(2026, 12, 26, 13, 0, tzinfo=pc.ET)

        deadline = pc.week_deadline(games, configured_deadline=configured)

        assert deadline == configured


class TestGamesWithIncludedFlags:
    """Persisting a real included/excluded flag per game (CP-8)."""

    def test_defaults_to_included_when_not_in_the_map(self):
        games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00")])

        result = pc.games_with_included_flags(games, {})

        assert bool(result.loc[0, "included"]) is True

    def test_respects_an_explicit_exclusion(self):
        games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00")])

        result = pc.games_with_included_flags(games, {"g1": False})

        assert bool(result.loc[0, "included"]) is False


class TestResolveWeekLock:
    """Deciding what to lock in once a week's deadline passes (CP-9/CP-10)."""

    def test_prefers_an_existing_saved_snapshot_over_recomputing(self):
        auto_games = pd.DataFrame(
            [_game("g1", 1, "Sunday", "13:00", home_moneyline=-900, away_moneyline=650)]
        )
        saved_games = pd.DataFrame([{"game_id": "g1", "included": 1}])
        saved_picks = pd.DataFrame(
            [{"game_id": "g1", "points": 1, "predicted_winner": "BBB", "confidence": 0.05}]
        )

        outcome = pc.resolve_week_lock(auto_games, {}, saved_games, saved_picks)

        assert outcome.locked is True
        assert outcome.warning is None
        # Reused as-is (BBB/0.05), not recomputed from auto_games' lopsided odds.
        assert outcome.picks.loc[0, "predicted_winner"] == "BBB"
        assert outcome.picks.loc[0, "confidence"] == pytest.approx(0.05)

    def test_computes_a_fresh_snapshot_when_nothing_was_ever_saved(self):
        auto_games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00")])
        empty = pd.DataFrame()

        outcome = pc.resolve_week_lock(auto_games, {}, empty, empty)

        assert outcome.locked is True
        assert outcome.warning is None
        assert list(outcome.picks["game_id"]) == ["g1"]

    def test_excludes_a_previously_unchecked_game_from_the_fresh_snapshot(self):
        auto_games = pd.DataFrame(
            [
                _game("keep", 1, "Sunday", "13:00"),
                _game("drop", 1, "Sunday", "13:00"),
            ]
        )
        empty = pd.DataFrame()

        outcome = pc.resolve_week_lock(auto_games, {"drop": False}, empty, empty)

        assert list(outcome.picks["game_id"]) == ["keep"]
        assert set(outcome.games["game_id"]) == {"keep", "drop"}
        assert bool(outcome.games.set_index("game_id").loc["drop", "included"]) is False

    def test_pending_odds_with_no_prior_snapshot_leaves_the_week_unlocked_with_a_warning(self):
        auto_games = pd.DataFrame(
            [_game("g1", 1, "Sunday", "13:00", home_moneyline=None, away_moneyline=None)]
        )
        empty = pd.DataFrame()

        outcome = pc.resolve_week_lock(auto_games, {}, empty, empty)

        assert outcome.locked is False
        assert outcome.warning is not None
        assert "g1" not in outcome.warning  # matches on team names, not game_id
        assert "BBB @ AAA" in outcome.warning


class TestIsFirstLookWindow:
    """Gates whether a save is close enough to kickoff to count as a real
    first look at a week, not a click-ahead preview of a future one."""

    def test_within_the_window_is_eligible(self):
        games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00", gameday="2026-09-13")])
        thursday = datetime(2026, 9, 10, 9, 0, tzinfo=pc.ET)  # 3 days before kickoff

        assert pc.is_first_look_window(games, thursday) is True

    def test_well_before_the_window_is_not_eligible(self):
        games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00", gameday="2026-09-13")])
        weeks_early = datetime(2026, 8, 20, 9, 0, tzinfo=pc.ET)

        assert pc.is_first_look_window(games, weeks_early) is False

    def test_the_day_after_the_window_boundary_is_not_eligible(self):
        games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00", gameday="2026-09-13")])
        wednesday = datetime(2026, 9, 9, 9, 0, tzinfo=pc.ET)  # 4 days before kickoff

        assert pc.is_first_look_window(games, wednesday) is False

    def test_on_or_after_kickoff_is_still_eligible(self):
        games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00", gameday="2026-09-13")])
        monday = datetime(2026, 9, 14, 9, 0, tzinfo=pc.ET)

        assert pc.is_first_look_window(games, monday) is True


class TestIsLocked:
    def test_before_deadline_is_not_locked(self):
        deadline = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)
        now = datetime(2026, 9, 13, 12, 59, tzinfo=pc.ET)

        assert pc.is_locked(now, deadline) is False

    def test_at_or_after_deadline_is_locked(self):
        deadline = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)
        now = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)

        assert pc.is_locked(now, deadline) is True
