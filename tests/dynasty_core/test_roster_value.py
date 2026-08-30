"""Tests for dynasty_core.roster_value."""

from __future__ import annotations

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestPlayerStatusDetails:
    """(icon, description) pairs for a player's situation - a player can have more than one."""

    def test_rookie_with_no_years_exp_is_flagged(self):
        info = {"years_exp": 0}
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids=set()) == [
            ("🆕", "Rookie (no NFL experience yet)")
        ]

    def test_established_healthy_active_player_has_no_flags(self):
        info = {"years_exp": 5, "injury_status": None}
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids=set()) == []

    def test_injury_status_uses_the_raw_word_for_a_clear_status(self):
        info = {"years_exp": 5, "injury_status": "Questionable"}
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids=set()) == [("🏥", "Questionable")]

    def test_injury_status_expands_a_cryptic_abbreviation(self):
        info = {"years_exp": 5, "injury_status": "PUP"}
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids=set()) == [
            ("🏥", "Physically Unable to Perform")
        ]

    def test_taxi_and_reserve_are_flagged_independently_of_roster_data(self):
        info = {"years_exp": 5}
        assert dc.player_status_details("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == [("🌱", "Taxi squad")]
        assert dc.player_status_details("p1", info, taxi_ids=set(), reserve_ids={"p1"}) == [
            ("🩹", "IR / Reserve")
        ]

    def test_multiple_flags_combine(self):
        # A rookie stashed on taxi who's also currently questionable.
        info = {"years_exp": 0, "injury_status": "Questionable"}
        assert dc.player_status_details("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == [
            ("🆕", "Rookie (no NFL experience yet)"),
            ("🏥", "Questionable"),
            ("🌱", "Taxi squad"),
        ]


class TestPlayerStatusFlags:
    """Compact icon-only summary of player_status_details, as a single string."""

    def test_icons_only_no_descriptions(self):
        info = {"years_exp": 0, "injury_status": "Questionable"}
        assert dc.player_status_flags("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == "🆕 🏥 🌱"

    def test_no_flags_is_an_empty_string(self):
        info = {"years_exp": 5, "injury_status": None}
        assert dc.player_status_flags("p1", info, taxi_ids=set(), reserve_ids=set()) == ""


class TestRosterValueAnalysisPhaseAwareNote:
    """The "low value, young - hold" exception should only fire while the
    team is rebuilding; otherwise a young low-value player falls through to
    the same aging-or-monitor read as anyone else."""

    def _roster(self):
        # 4 players so the bottom-quartile cutoff (max(3, len // 4)) is
        # exactly 3 - all three of the low-value rows below get flagged.
        players = {
            "young_low": make_player("WR", full_name="Young Low"),
            "aging_low": make_player("RB", full_name="Aging Low"),
            "mid_low": make_player("WR", full_name="Mid Low"),
            "high_value": make_player("QB", full_name="High Value"),
        }
        players["young_low"]["age"] = 21
        players["young_low"]["years_exp"] = 1
        players["aging_low"]["age"] = 30  # >= LOW_VALUE_AGING_AGE["RB"] (27)
        players["aging_low"]["years_exp"] = 6
        players["mid_low"]["age"] = 26  # young, but not < LOW_VALUE_YOUNG_AGE (24)
        players["mid_low"]["years_exp"] = 4
        players["high_value"]["age"] = 28
        players["high_value"]["years_exp"] = 5
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("young_low", 10),
                fc_entry("aging_low", 11),
                fc_entry("mid_low", 12),
                fc_entry("high_value", 900),
            ]
        )
        roster = {"players": list(players.keys())}
        return roster, players, fc_by_id

    def test_young_low_value_player_is_a_hold_while_rebuilding(self):
        roster, players, fc_by_id = self._roster()

        result = dc.roster_value_analysis(roster, players, fc_by_id, phase="rebuilding")

        note = result.set_index("name")["note"]
        assert note["Young Low"] == "Low value, young — rebuild upside, hold"
        assert note["Aging Low"] == "Low value, aging — drop candidate"
        assert note["Mid Low"] == "Low value — monitor"

    def test_young_low_value_player_loses_the_hold_once_not_rebuilding(self):
        roster, players, fc_by_id = self._roster()

        result = dc.roster_value_analysis(roster, players, fc_by_id, phase="contending")

        note = result.set_index("name")["note"]
        # Too young to clear the aging cutoff either, so it falls through
        # to "monitor" - not silently promoted to "drop candidate".
        assert note["Young Low"] == "Low value — monitor"
        assert note["Aging Low"] == "Low value, aging — drop candidate"
        assert note["Mid Low"] == "Low value — monitor"

    def test_default_phase_matches_explicit_rebuilding(self):
        roster, players, fc_by_id = self._roster()

        default_result = dc.roster_value_analysis(roster, players, fc_by_id)
        explicit_result = dc.roster_value_analysis(roster, players, fc_by_id, phase="rebuilding")

        assert list(default_result["note"]) == list(explicit_result["note"])
