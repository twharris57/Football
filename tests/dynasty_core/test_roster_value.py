"""Tests for dynasty_core.roster_value."""

from __future__ import annotations

import dynasty_core as dc


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
    """Compact icon-only summary of player_status_details, for plain-text display (the CLI)."""

    def test_icons_only_no_descriptions(self):
        info = {"years_exp": 0, "injury_status": "Questionable"}
        assert dc.player_status_flags("p1", info, taxi_ids={"p1"}, reserve_ids=set()) == "🆕 🏥 🌱"

    def test_no_flags_is_an_empty_string(self):
        info = {"years_exp": 5, "injury_status": None}
        assert dc.player_status_flags("p1", info, taxi_ids=set(), reserve_ids=set()) == ""
