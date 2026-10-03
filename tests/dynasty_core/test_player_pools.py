"""Tests for dynasty_core.player_pools."""

from __future__ import annotations

import pytest

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestFantasyRelevantTeamedPlayers:
    """Every fantasy-position player on an NFL team, rostered or not."""

    def test_includes_rostered_players_unlike_free_agent_pool(self):
        players = {
            "rostered_wr": make_player("WR", full_name="Rostered WR"),
            "free_wr": make_player("WR", full_name="Free WR"),
        }

        universe = dc.fantasy_relevant_teamed_players(players)

        assert set(universe.keys()) == {"rostered_wr", "free_wr"}

    def test_excludes_players_with_no_real_nfl_team(self):
        players = {
            "no_team": {"position": "WR", "team": None, "full_name": "No Team"},
            "on_team": make_player("WR", full_name="On Team"),
        }

        universe = dc.fantasy_relevant_teamed_players(players)

        assert set(universe.keys()) == {"on_team"}

    def test_excludes_non_fantasy_positions(self):
        players = {
            "kicker": {"position": "K", "team": "AAA", "full_name": "A Kicker"},
            "wr": make_player("WR", full_name="A WR"),
        }

        universe = dc.fantasy_relevant_teamed_players(players)

        assert set(universe.keys()) == {"wr"}


class TestFreeAgentPool:
    """free_agent_pool should be every fantasy-relevant, real-NFL-team player not on any roster."""

    def test_excludes_rostered_players(self):
        players = {
            "rostered_wr": make_player("WR", full_name="Rostered WR"),
            "free_wr": make_player("WR", full_name="Free WR"),
        }
        rosters = [{"roster_id": 1, "players": ["rostered_wr"]}]

        pool = dc.free_agent_pool(players, rosters)

        assert set(pool.keys()) == {"free_wr"}

    def test_excludes_players_with_no_real_nfl_team(self):
        # Sleeper's player dataset carries retired/practice-squad-only/no-team
        # entries that would otherwise flood the pool with irrelevant results.
        players = {
            "no_team": {"position": "WR", "team": None, "full_name": "No Team"},
            "on_team": make_player("WR", full_name="On Team"),
        }

        pool = dc.free_agent_pool(players, [])

        assert set(pool.keys()) == {"on_team"}

    def test_excludes_non_fantasy_positions(self):
        players = {
            "kicker": {"position": "K", "team": "AAA", "full_name": "A Kicker"},
            "wr": make_player("WR", full_name="A WR"),
        }

        pool = dc.free_agent_pool(players, [])

        assert set(pool.keys()) == {"wr"}

    def test_excludes_draft_eligible_rookies_mid_draft(self):
        # Undrafted rookies are excluded while the draft is live.
        players = {
            "rookie_wr": make_player("WR", full_name="Undrafted Rookie"),
            "veteran_wr": make_player("WR", full_name="Veteran FA"),
        }

        pool = dc.free_agent_pool(players, [], draft_eligible_rookie_ids=frozenset({"rookie_wr"}))

        assert set(pool.keys()) == {"veteran_wr"}

    def test_undrafted_rookie_becomes_a_real_free_agent_once_draft_is_complete(self):
        # Once the draft ends, the same rookie is a free agent.
        players = {"rookie_wr": make_player("WR", full_name="Undrafted Rookie")}

        pool = dc.free_agent_pool(players, [], draft_eligible_rookie_ids=frozenset())

        assert set(pool.keys()) == {"rookie_wr"}


class TestPersonalizedMultipliers:
    """fc_value_by_sleeper_id should prefer a per-player multiplier (see player_scoring.py)
    over the position average, and fall back sensibly when one isn't available."""

    def test_personalized_multiplier_preferred_over_position_average(self):
        multipliers = {"per_player": {"qb1": 2.0}, "position_average": {"QB": 1.5}}

        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")], multipliers)

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(200.0)

    def test_rookie_bucket_preferred_over_position_average(self):
        multipliers = {"per_player": {}, "rookie_bucket": {"qb1": 1.3}, "position_average": {"QB": 1.5}}

        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")], multipliers)

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(130.0)

    def test_personalized_multiplier_preferred_over_rookie_bucket(self):
        multipliers = {"per_player": {"qb1": 2.0}, "rookie_bucket": {"qb1": 1.3}, "position_average": {"QB": 1.5}}

        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")], multipliers)

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(200.0)

    def test_falls_back_to_position_average_when_no_personalized_entry(self):
        multipliers = {"per_player": {}, "position_average": {"QB": 1.5}}

        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")], multipliers)

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(150.0)

    def test_falls_back_to_hardcoded_constant_when_no_multipliers_available(self):
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("qb1", 100, position="QB")])

        assert fc_by_id["qb1"]["adj_value"] == pytest.approx(100 * dc.POSITION_VALUE_MULTIPLIER["QB"])
