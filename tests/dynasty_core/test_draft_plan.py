"""Tests for dynasty_core.draft_plan."""

from __future__ import annotations

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


class TestMultiRoundPlan:
    """End-to-end: multi_round_plan should fill a true positional need before a
    same-position depth upgrade, and carry each round's pick into the next."""

    def test_fills_empty_starting_slot_before_a_same_position_upgrade(self):
        league = {"roster_positions": ["QB", "WR", "BN"], "settings": {"taxi_slots": 0}}
        players = {
            "old_wr": make_player("WR", full_name="Old WR"),
            "good_qb": make_player("QB", full_name="Good QB"),
            "good_wr": make_player("WR", full_name="Good WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("old_wr", 50, position="WR"),
                fc_entry("good_qb", 300, position="QB"),
                fc_entry("good_wr", 100, position="WR"),
            ]
        )
        user_roster = {"players": ["old_wr"], "taxi": [], "reserve": []}
        ownership = [
            dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=1),
            dc.DraftPickSlot(round=2, overall_pick=2, original_roster_id=1, owner_roster_id=1),
        ]
        available = {"good_qb": players["good_qb"], "good_wr": players["good_wr"]}

        plan = dc.multi_round_plan(
            ownership=ownership,
            user_roster_id=1,
            current_pick_no=1,
            available=available,
            players=players,
            fc_by_sleeper_id=fc_by_id,
            user_roster=user_roster,
            league=league,
            byes={},
            handcuffs={},
            real_picks_by_overall={},
        )

        rounds = plan["rounds"]
        # Round 1 fills the completely-empty QB slot (marginal +300) rather
        # than a modest WR depth upgrade (marginal +50 - old_wr stays
        # started either way, just at a higher value).
        assert rounds.iloc[0]["pick_name"] == "Good QB"
        assert rounds.iloc[0]["status"] == "upcoming"
        # Round 2 correctly builds on round 1's pick, taking the only
        # remaining candidate.
        assert rounds.iloc[1]["pick_name"] == "Good WR"
        # Exactly at capacity (3 players, 3 slots, no taxi) - never over it,
        # so no drop should have been forced in either round.
        assert rounds["drop_name"].isna().all()
        # Adding a QB can only improve the roster's weekly gaps, never worsen
        # them - no new/worse gap alerts expected.
        assert plan["weekly_gap_alerts"].empty

    def test_all_candidates_by_pick_includes_every_evaluated_option(self):
        # rank_by_marginal_value already scores every candidate before
        # picking a winner - all_candidates_by_pick should expose all of
        # them (for a UI lookup), not just the one recommended pick.
        league = {"roster_positions": ["QB", "WR", "BN"], "settings": {"taxi_slots": 0}}
        players = {
            "old_wr": make_player("WR", full_name="Old WR"),
            "good_qb": make_player("QB", full_name="Good QB"),
            "good_wr": make_player("WR", full_name="Good WR"),
        }
        fc_by_id = dc.fc_value_by_sleeper_id(
            [
                fc_entry("old_wr", 50, position="WR"),
                fc_entry("good_qb", 300, position="QB"),
                fc_entry("good_wr", 100, position="WR"),
            ]
        )
        user_roster = {"players": ["old_wr"], "taxi": [], "reserve": []}
        ownership = [dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=1)]
        available = {"good_qb": players["good_qb"], "good_wr": players["good_wr"]}

        plan = dc.multi_round_plan(
            ownership=ownership,
            user_roster_id=1,
            current_pick_no=1,
            available=available,
            players=players,
            fc_by_sleeper_id=fc_by_id,
            user_roster=user_roster,
            league=league,
            byes={},
            handcuffs={},
            real_picks_by_overall={},
        )

        candidates = plan["all_candidates_by_pick"][1]
        assert set(candidates["name"]) == {"Good QB", "Good WR"}
        # Both evaluated candidates are present and correctly ordered by
        # marginal value, not just the one actually recommended.
        assert candidates.iloc[0]["name"] == "Good QB"
        assert candidates.iloc[0]["marginal_value"] > candidates.iloc[1]["marginal_value"]
