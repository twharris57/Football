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


class TestExplainOdds:
    """Intermediate de-vig math behind a pick's confidence score -- the
    same values rank_games uses internally, exposed for the UI's detail view."""

    def test_probabilities_are_normalized_to_sum_to_one(self):
        explanation = pc.explain_odds(home_moneyline=-150, away_moneyline=130)

        assert explanation.home_prob + explanation.away_prob == pytest.approx(1.0)

    def test_raw_probabilities_precede_normalization(self):
        explanation = pc.explain_odds(home_moneyline=-150, away_moneyline=130)

        assert explanation.home_prob_raw == pytest.approx(pc.compute_probability(-150))
        assert explanation.away_prob_raw == pytest.approx(pc.compute_probability(130))
        assert explanation.home_prob_raw + explanation.away_prob_raw > 1.0

    def test_confidence_matches_rank_games_for_the_same_game(self):
        games = pd.DataFrame(
            [_game("g1", 1, "Sunday", "13:00", home_moneyline=-150, away_moneyline=130)]
        )
        ranked, _ = pc.rank_games(games)

        explanation = pc.explain_odds(home_moneyline=-150, away_moneyline=130)

        assert explanation.confidence == pytest.approx(ranked.loc[0, "confidence"])


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
                _game("thu", 1, "Thursday", "20:20", gameday="2026-09-10"),
                _game("early_sun", 1, "Sunday", "09:30"),
                _game("kept", 1, "Sunday", "13:00"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 1)

        assert set(selected["game_id"]) == {"kept"}

    def test_includes_a_tuesday_makeup_game(self):
        # A weather-postponed game moved to Tuesday still counts -- it
        # kicks off well after the deadline, same no-leak reasoning as a
        # Monday game, which a weekday-enum check (Monday/Sunday only)
        # would have silently missed.
        schedule = pd.DataFrame(
            [
                _game("tue_makeup", 1, "Tuesday", "19:00", gameday="2026-09-15"),
                _game("sun_afternoon", 1, "Sunday", "13:00"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 1)

        assert set(selected["game_id"]) == {"tue_makeup", "sun_afternoon"}

    def test_excludes_a_game_the_wednesday_after(self):
        schedule = pd.DataFrame(
            [
                _game("wed", 1, "Wednesday", "19:00", gameday="2026-09-16"),
                _game("sun_afternoon", 1, "Sunday", "13:00"),
            ]
        )

        selected = pc.select_games(schedule, 2026, 1)

        assert set(selected["game_id"]) == {"sun_afternoon"}

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

    def test_all_games_rule_excludes_a_game_before_a_configured_deadline(self):
        # Once a real deadline is known, 'all_games' should stop assuming
        # it predates every kickoff that week and actually check.
        schedule = pd.DataFrame(
            [
                _game("early", 17, "Thursday", "20:00", gameday="2026-12-24"),
                _game("sat", 17, "Saturday", "13:00", gameday="2026-12-26"),
            ]
        )
        deadline = datetime(2026, 12, 26, 13, 0, tzinfo=pc.ET)

        selected = pc.select_games(
            schedule, 2026, 17, selection_rule="all_games", configured_deadline=deadline
        )

        assert set(selected["game_id"]) == {"sat"}

    def test_standard_rule_is_the_default(self):
        schedule = pd.DataFrame(
            [
                _game("sat", 17, "Saturday", "16:30", gameday="2026-09-12"),
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


class TestWeekDateLabels:
    """Human date spans per week, for labeling a week selector."""

    def test_single_day_week(self):
        schedule = pd.DataFrame([_game("g1", 1, "Sunday", "13:00", gameday="2026-09-13")])

        assert pc.week_date_labels(schedule) == {1: "Sep 13"}

    def test_multi_day_week_same_month(self):
        schedule = pd.DataFrame(
            [
                _game("g1", 1, "Thursday", "20:20", gameday="2026-09-10"),
                _game("g2", 1, "Monday", "20:15", gameday="2026-09-14"),
            ]
        )

        assert pc.week_date_labels(schedule) == {1: "Sep 10-14"}

    def test_multi_day_week_spanning_months(self):
        schedule = pd.DataFrame(
            [
                _game("g1", 18, "Saturday", "16:30", gameday="2027-01-02"),
                _game("g2", 18, "Sunday", "13:00", gameday="2027-01-03"),
                _game("g3", 18, "Wednesday", "20:00", gameday="2026-12-30"),
            ]
        )

        assert pc.week_date_labels(schedule) == {18: "Dec 30-Jan 3"}

    def test_excludes_non_regular_season_weeks(self):
        schedule = pd.DataFrame(
            [
                _game("reg", 1, "Sunday", "13:00", gameday="2026-09-13", game_type="REG"),
                _game("playoff", 1, "Sunday", "13:00", gameday="2027-01-10", game_type="WC"),
            ]
        )

        assert pc.week_date_labels(schedule) == {1: "Sep 13"}


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
        saved_games = pd.DataFrame(
            [{"game_id": "g1", "included": 1, "captured_at": "2026-09-10T09:00:00-04:00"}]
        )
        saved_picks = pd.DataFrame(
            [{"game_id": "g1", "points": 1, "predicted_winner": "BBB", "confidence": 0.05}]
        )
        now = datetime(2026, 9, 14, 13, 0, tzinfo=pc.ET)

        outcome = pc.resolve_week_lock(auto_games, {}, saved_games, saved_picks, now)

        assert outcome.locked is True
        assert outcome.warning is None
        # Reused as-is (BBB/0.05), not recomputed from auto_games' lopsided odds.
        assert outcome.picks.loc[0, "predicted_winner"] == "BBB"
        assert outcome.picks.loc[0, "confidence"] == pytest.approx(0.05)

    def test_reusing_a_saved_snapshot_persists_its_own_original_timestamp_not_now(self):
        # CP-25: locking in a prior snapshot must not overwrite its true
        # generation time with whatever moment the lock happens to run.
        auto_games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00")])
        saved_games = pd.DataFrame(
            [{"game_id": "g1", "included": 1, "captured_at": "2026-09-10T09:00:00-04:00"}]
        )
        saved_picks = pd.DataFrame(
            [{"game_id": "g1", "points": 1, "predicted_winner": "AAA", "confidence": 0.2}]
        )
        lock_time = datetime(2026, 9, 14, 13, 0, tzinfo=pc.ET)  # days after the real generation

        outcome = pc.resolve_week_lock(auto_games, {}, saved_games, saved_picks, lock_time)

        assert outcome.generated_at == datetime.fromisoformat("2026-09-10T09:00:00-04:00")
        assert outcome.generated_at != lock_time

    def test_computes_a_fresh_snapshot_when_nothing_was_ever_saved(self):
        auto_games = pd.DataFrame([_game("g1", 1, "Sunday", "13:00")])
        empty = pd.DataFrame()
        now = datetime(2026, 9, 13, 12, 0, tzinfo=pc.ET)  # before the 13:00 kickoff

        outcome = pc.resolve_week_lock(auto_games, {}, empty, empty, now)

        assert outcome.locked is True
        assert outcome.warning is None
        assert list(outcome.picks["game_id"]) == ["g1"]
        # No prior snapshot to reuse -- generated_at is genuinely "now".
        assert outcome.generated_at == now

    def test_warns_when_the_fresh_snapshot_is_computed_after_kickoff(self):
        # CP-15: the app was never opened for this week until well after its
        # deadline -- possibly after some of its games have already started.
        auto_games = pd.DataFrame(
            [
                _game("started", 1, "Sunday", "13:00", home_team="AAA", away_team="BBB"),
                _game("not_yet", 1, "Sunday", "20:20", home_team="CCC", away_team="DDD"),
            ]
        )
        empty = pd.DataFrame()
        now = datetime(2026, 9, 13, 16, 0, tzinfo=pc.ET)  # after the 13:00 kickoff, before 20:20

        outcome = pc.resolve_week_lock(auto_games, {}, empty, empty, now)

        assert outcome.locked is True  # still locks -- no better data to fall back to
        assert outcome.warning is not None
        assert "BBB @ AAA" in outcome.warning
        assert "DDD @ CCC" not in outcome.warning  # hasn't kicked off yet

    def test_no_stale_kickoff_warning_for_an_excluded_game_that_already_started(self):
        auto_games = pd.DataFrame(
            [_game("g1", 1, "Sunday", "13:00", home_team="AAA", away_team="BBB")]
        )
        empty = pd.DataFrame()
        now = datetime(2026, 9, 13, 16, 0, tzinfo=pc.ET)

        outcome = pc.resolve_week_lock(auto_games, {"g1": False}, empty, empty, now)

        assert outcome.warning is None

    def test_excludes_a_previously_unchecked_game_from_the_fresh_snapshot(self):
        auto_games = pd.DataFrame(
            [
                _game("keep", 1, "Sunday", "13:00"),
                _game("drop", 1, "Sunday", "13:00"),
            ]
        )
        empty = pd.DataFrame()
        now = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)

        outcome = pc.resolve_week_lock(auto_games, {"drop": False}, empty, empty, now)

        assert list(outcome.picks["game_id"]) == ["keep"]
        assert set(outcome.games["game_id"]) == {"keep", "drop"}
        assert bool(outcome.games.set_index("game_id").loc["drop", "included"]) is False

    def test_pending_odds_with_no_prior_snapshot_leaves_the_week_unlocked_with_a_warning(self):
        auto_games = pd.DataFrame(
            [_game("g1", 1, "Sunday", "13:00", home_moneyline=None, away_moneyline=None)]
        )
        empty = pd.DataFrame()
        now = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)

        outcome = pc.resolve_week_lock(auto_games, {}, empty, empty, now)

        assert outcome.locked is False
        assert outcome.warning is not None
        assert outcome.generated_at is None
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


class TestCheckActualPicks:
    """Flagging (never blocking) the real-world irregularities the Legion
    pool bylaws define an explicit resolution for, not exclusion."""

    def test_clean_submission_has_no_issues(self):
        entries = {"g1": ("KC", 1), "g2": ("BUF", 2)}

        assert pc.check_actual_picks(entries) == []

    def test_unmarked_winner_is_flagged_as_rule_16(self):
        entries = {"g1": (None, 1)}

        issues = pc.check_actual_picks(entries)

        assert len(issues) == 1
        assert "rule 16" in issues[0]

    def test_blank_points_is_flagged_as_rule_15(self):
        entries = {"g1": ("KC", None)}

        issues = pc.check_actual_picks(entries)

        assert len(issues) == 1
        assert "rule 15" in issues[0]

    def test_duplicate_points_is_flagged_as_rule_7(self):
        entries = {"g1": ("KC", 1), "g2": ("BUF", 1)}

        issues = pc.check_actual_picks(entries)

        assert len(issues) == 1
        assert "rule 7" in issues[0]

    def test_late_is_flagged_as_rule_2(self):
        entries = {"g1": ("KC", 1)}

        issues = pc.check_actual_picks(entries, late=True)

        assert len(issues) == 1
        assert "rule 2" in issues[0]

    def test_multiple_issues_are_all_reported(self):
        entries = {"g1": (None, 1), "g2": ("BUF", 1)}

        issues = pc.check_actual_picks(entries, late=True)

        assert len(issues) == 3  # late, unmarked winner, duplicate points

    def test_messages_use_team_names_when_given(self):
        entries = {"g1": (None, 1)}

        issues = pc.check_actual_picks(entries, team_names={"g1": "Chiefs @ Bills"})

        assert "Chiefs @ Bills" in issues[0]


def _outcomes(*rows):
    """rows: (game_id, home_team, away_team, home_score, away_score)."""
    return pd.DataFrame(
        rows, columns=["game_id", "home_team", "away_team", "home_score", "away_score"]
    )


class TestScorePicks:
    """Scoring a set of picks (algorithm's or actual submission's -- same
    shape) against real outcomes, applying bylaws rules 6/7/15/16."""

    def test_correct_pick_awards_its_points(self):
        entries = {"g1": ("KC", 3)}
        outcomes = _outcomes(("g1", "KC", "BUF", 27, 20))

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 3
        assert score.games_decided == 1
        assert score.games_total == 1
        assert score.results[0].correct is True
        assert score.results[0].points_awarded == 3

    def test_incorrect_pick_awards_nothing(self):
        entries = {"g1": ("BUF", 3)}
        outcomes = _outcomes(("g1", "KC", "BUF", 27, 20))

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 0
        assert score.results[0].correct is False

    def test_tied_game_awards_no_points_regardless_of_pick(self):
        # Bylaws rule 6: "all points picked in games ending in a tie will be lost."
        entries = {"g1": ("KC", 5)}
        outcomes = _outcomes(("g1", "KC", "BUF", 24, 24))

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 0
        assert score.results[0].actual_winner is None
        assert score.results[0].correct is False
        assert score.results[0].decided is True

    def test_blank_winner_is_scored_as_incorrect(self):
        # Bylaws rule 16.
        entries = {"g1": (None, 3)}
        outcomes = _outcomes(("g1", "KC", "BUF", 27, 20))

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 0
        assert score.results[0].correct is False

    def test_blank_points_awards_nothing_even_when_correct(self):
        # Bylaws rule 15.
        entries = {"g1": ("KC", None)}
        outcomes = _outcomes(("g1", "KC", "BUF", 27, 20))

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 0
        assert score.results[0].correct is True
        assert score.results[0].points_awarded == 0

    def test_duplicate_points_credited_once_when_one_game_correct(self):
        # Bylaws rule 7: a shared points value counts once, not per game.
        entries = {"g1": ("KC", 3), "g2": ("SF", 3)}
        outcomes = _outcomes(
            ("g1", "KC", "BUF", 27, 20),  # correct
            ("g2", "SF", "LA", 10, 24),  # SF picked, LA actually won -- incorrect
        )

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 3

    def test_duplicate_points_credited_only_once_when_both_correct(self):
        entries = {"g1": ("KC", 3), "g2": ("SF", 3)}
        outcomes = _outcomes(
            ("g1", "KC", "BUF", 27, 20),
            ("g2", "SF", "LA", 24, 10),
        )

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 3  # not 6

    def test_duplicate_points_awards_nothing_when_neither_correct(self):
        entries = {"g1": ("BUF", 3), "g2": ("LA", 3)}
        outcomes = _outcomes(
            ("g1", "KC", "BUF", 27, 20),
            ("g2", "SF", "LA", 24, 10),
        )

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 0

    def test_undecided_game_is_excluded_from_the_total_but_still_counted(self):
        entries = {"g1": ("KC", 3), "g2": ("SF", 2)}
        outcomes = _outcomes(
            ("g1", "KC", "BUF", 27, 20),
            ("g2", "SF", "LA", None, None),  # not played yet
        )

        score = pc.score_picks(entries, outcomes)

        assert score.total_points == 3
        assert score.games_decided == 1
        assert score.games_total == 2

    def test_game_missing_from_outcomes_entirely_is_treated_as_undecided(self):
        entries = {"g1": ("KC", 3)}
        outcomes = _outcomes()

        score = pc.score_picks(entries, outcomes)

        assert score.games_decided == 0
        assert score.games_total == 1
        assert score.results[0].decided is False


class TestCheckReportedScore:
    """Cross-checking the pool's officially reported score against this
    app's own computed total -- the interim stand-in for bylaws rule 2's
    unresolvable late-card penalty."""

    def _week_score(self, total_points, games_decided=1, games_total=1):
        return pc.WeekScore(
            total_points=total_points, games_decided=games_decided,
            games_total=games_total, results=[],
        )

    def test_no_reported_score_yet_is_not_flagged(self):
        assert pc.check_reported_score(self._week_score(10), None, late=False) is None

    def test_incomplete_week_is_not_flagged(self):
        score = self._week_score(10, games_decided=1, games_total=2)

        assert pc.check_reported_score(score, 99, late=False) is None

    def test_late_card_is_never_flagged_even_on_mismatch(self):
        # Rule 2's real penalty isn't verifiable without the field's scores.
        score = self._week_score(10)

        assert pc.check_reported_score(score, 0, late=True) is None

    def test_matching_score_is_not_flagged(self):
        score = self._week_score(10)

        assert pc.check_reported_score(score, 10, late=False) is None

    def test_mismatched_score_is_flagged(self):
        score = self._week_score(10)

        message = pc.check_reported_score(score, 7, late=False)

        assert message is not None
        assert "10" in message
        assert "7" in message

    def test_a_reported_score_of_zero_matching_a_zero_total_is_not_flagged(self):
        # A genuinely all-wrong week -- 0 is a real value here, not "unset"
        # (see CP-31; store.set_reported_score/get_week_status already
        # distinguish 0 from None, this checks the comparison itself).
        score = self._week_score(0)

        assert pc.check_reported_score(score, 0, late=False) is None

    def test_a_negative_reported_score_is_compared_normally(self):
        # Rule 2's late-card penalty can go negative; the comparison itself
        # doesn't need special-casing for that, only the late=True branch
        # (already covered) suppresses the flag.
        score = self._week_score(5)

        message = pc.check_reported_score(score, -3, late=False)

        assert message is not None
        assert "-3" in message


class TestIsLocked:
    def test_before_deadline_is_not_locked(self):
        deadline = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)
        now = datetime(2026, 9, 13, 12, 59, tzinfo=pc.ET)

        assert pc.is_locked(now, deadline) is False

    def test_at_or_after_deadline_is_locked(self):
        deadline = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)
        now = datetime(2026, 9, 13, 13, 0, tzinfo=pc.ET)

        assert pc.is_locked(now, deadline) is True
