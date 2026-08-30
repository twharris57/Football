"""Tests for dynasty_core.draft_plan."""

from __future__ import annotations

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player

# A never-reconciled snapshot - every completed round falls back to the
# live-guess heuristic, matching this project's pre-RT-20 behavior.
EMPTY_SNAPSHOT = {"confirmed_through_pick": 0, "confirmed_roster": None, "confirmed_drops": {}}


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
            draft_snapshot=EMPTY_SNAPSHOT,
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

    def test_flagged_need_reason_follows_weak_once_not_rebuilding(self):
        # Existing roster has 2 young (years_exp <= 2) but low-value RBs -
        # young-core count (2) already meets YOUNG_CORE_NEED_THRESHOLD (no
        # need while rebuilding), but RB is well below replacement_level
        # (weak - a need once the team isn't framing itself as a rebuild).
        league = {"roster_positions": ["RB", "BN"], "settings": {"taxi_slots": 0}}
        players = {
            "rb_a": make_player("RB", full_name="RB A"),
            "rb_b": make_player("RB", full_name="RB B"),
            "good_rb": make_player("RB", full_name="Good RB"),
        }
        # years_exp <= YOUNG_CORE_MAX_YOE for both existing RBs, so young_core
        # (2) already meets YOUNG_CORE_NEED_THRESHOLD (2) - not a young-core
        # need while rebuilding.
        players["rb_a"]["years_exp"] = 1
        players["rb_b"]["years_exp"] = 1
        fc_by_id = dc.fc_value_by_sleeper_id(
            [fc_entry("rb_a", 5, position="RB"), fc_entry("rb_b", 5, position="RB"), fc_entry("good_rb", 100, position="RB")]
        )
        user_roster = {"players": ["rb_a", "rb_b"], "taxi": [], "reserve": []}
        ownership = [dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=1)]
        available = {"good_rb": players["good_rb"]}
        replacement_level = {"QB": 0.0, "RB": 200.0, "WR": 0.0, "TE": 0.0}

        rebuilding_plan = dc.multi_round_plan(
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
            draft_snapshot=EMPTY_SNAPSHOT,
            replacement_level=replacement_level,
            phase="rebuilding",
        )
        contending_plan = dc.multi_round_plan(
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
            draft_snapshot=EMPTY_SNAPSHOT,
            replacement_level=replacement_level,
            phase="contending",
        )

        assert "flagged need" not in rebuilding_plan["rounds"].iloc[0]["reason"]
        assert "also a flagged need at RB" in contending_plan["rounds"].iloc[0]["reason"]

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
            draft_snapshot=EMPTY_SNAPSHOT,
        )

        candidates = plan["all_candidates_by_pick"][1]
        assert set(candidates["name"]) == {"Good QB", "Good WR"}
        # Both evaluated candidates are present and correctly ordered by
        # marginal value, not just the one actually recommended.
        assert candidates.iloc[0]["name"] == "Good QB"
        assert candidates.iloc[0]["marginal_value"] > candidates.iloc[1]["marginal_value"]


class TestRealDropReconciliation:
    """RT-20: a completed round's drop should reflect draft_snapshot's real,
    recovered data when available, instead of always trusting the live-guess
    heuristic - and later rounds should simulate forward from that real
    state, not a chain of guesses."""

    LEAGUE = {"roster_positions": ["QB", "WR", "BN"], "settings": {"taxi_slots": 0}}
    PLAYERS = {
        "old_wr": make_player("WR", full_name="Old WR"),
        "filler": make_player("WR", full_name="Filler"),
        "extra": make_player("WR", full_name="Extra"),
        "good_qb": make_player("QB", full_name="Good QB"),
        "taxi_stud": make_player("WR", full_name="Taxi Stud"),
    }
    FC_BY_ID = dc.fc_value_by_sleeper_id(
        [
            fc_entry("old_wr", 50, position="WR"),
            fc_entry("filler", 100, position="WR"),
            fc_entry("extra", 10, position="WR"),
            fc_entry("good_qb", 300, position="QB"),
            fc_entry("taxi_stud", 500, position="WR"),
        ]
    )
    OWNERSHIP = [
        dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=1),
        dc.DraftPickSlot(round=2, overall_pick=2, original_roster_id=1, owner_roster_id=1),
    ]
    REAL_PICKS_BY_OVERALL = {1: "good_qb"}

    def test_confirmed_real_drop_overrides_the_heuristic_guess(self):
        # Roster is at capacity exactly (2 players + 1 pick = 3 slots), so
        # the heuristic itself wouldn't force any drop here - the confirmed
        # override should still win.
        user_roster = {"players": ["old_wr", "filler"], "taxi": [], "reserve": []}
        draft_snapshot = {
            "confirmed_through_pick": 1,
            "confirmed_roster": ["old_wr", "good_qb"],
            "confirmed_drops": {"1": "filler"},
        }

        plan = dc.multi_round_plan(
            ownership=self.OWNERSHIP,
            user_roster_id=1,
            current_pick_no=2,
            available={},
            players=self.PLAYERS,
            fc_by_sleeper_id=self.FC_BY_ID,
            user_roster=user_roster,
            league=self.LEAGUE,
            byes={},
            handcuffs={},
            real_picks_by_overall=self.REAL_PICKS_BY_OVERALL,
            draft_snapshot=draft_snapshot,
        )

        round1 = plan["rounds"].iloc[0]
        assert round1["drop_status"] == "confirmed"
        assert round1["drop_name"] == "Filler"
        # Filler (100) outvalues Old WR (50) for the one WR slot, so it was
        # a real starter entering this round.
        assert bool(round1["drop_is_starter"]) is True

    def test_confirmed_roster_feeds_forward_instead_of_a_simulated_guess(self):
        user_roster = {"players": ["old_wr", "filler"], "taxi": [], "reserve": []}
        # Deliberately different from what the naive simulated update
        # (drop filler, append good_qb) would have produced - proves the
        # next round starts from the confirmed real roster, not a guess.
        draft_snapshot = {
            "confirmed_through_pick": 1,
            "confirmed_roster": ["surprise"],
            "confirmed_drops": {"1": "filler"},
        }

        plan = dc.multi_round_plan(
            ownership=self.OWNERSHIP,
            user_roster_id=1,
            current_pick_no=2,
            # hypothetical_ids_by_pick[2] is snapshotted before round 2's
            # own candidate ranking runs, so no real round-2 candidates are
            # needed to observe the feed-forward result.
            available={},
            players=self.PLAYERS,
            fc_by_sleeper_id=self.FC_BY_ID,
            user_roster=user_roster,
            league=self.LEAGUE,
            byes={},
            handcuffs={},
            real_picks_by_overall=self.REAL_PICKS_BY_OVERALL,
            draft_snapshot=draft_snapshot,
        )

        assert plan["hypothetical_ids_by_pick"][2] == ["surprise"]

    def test_ambiguous_round_keeps_the_heuristic_guess_but_still_feeds_forward(self):
        # Over capacity (3 players + 1 pick = 4 > 3 slots), so the heuristic
        # must recommend a real drop - the lowest-value bench player, Extra.
        user_roster = {"players": ["old_wr", "filler", "extra"], "taxi": [], "reserve": []}
        draft_snapshot = {
            "confirmed_through_pick": 1,
            "confirmed_roster": ["surprise"],
            "confirmed_drops": {"1": dc.AMBIGUOUS},
        }

        plan = dc.multi_round_plan(
            ownership=self.OWNERSHIP,
            user_roster_id=1,
            current_pick_no=2,
            # hypothetical_ids_by_pick[2] is snapshotted before round 2's
            # own candidate ranking runs, so no real round-2 candidates are
            # needed to observe the feed-forward result.
            available={},
            players=self.PLAYERS,
            fc_by_sleeper_id=self.FC_BY_ID,
            user_roster=user_roster,
            league=self.LEAGUE,
            byes={},
            handcuffs={},
            real_picks_by_overall=self.REAL_PICKS_BY_OVERALL,
            draft_snapshot=draft_snapshot,
        )

        round1 = plan["rounds"].iloc[0]
        assert round1["drop_status"] == "ambiguous"
        assert round1["drop_name"] == "Extra"
        # The confirmed frontier still advances (and feeds forward) even
        # though this specific round's drop couldn't be isolated.
        assert plan["hypothetical_ids_by_pick"][2] == ["surprise"]

    def test_confirmed_drop_is_starter_ignores_taxi_players_value(self):
        # A taxi player can never actually occupy a starting slot, no matter
        # how high its value - it must not be able to "steal" the WR slot
        # from the real active-roster starter in this is_starter check and
        # mask that the confirmed drop really was a starter (fix-before-merge
        # finding from the 2026-08-07 valuation review).
        user_roster = {"players": ["old_wr", "filler", "taxi_stud"], "taxi": ["taxi_stud"], "reserve": []}
        draft_snapshot = {
            "confirmed_through_pick": 1,
            "confirmed_roster": ["old_wr", "good_qb", "taxi_stud"],
            "confirmed_drops": {"1": "filler"},
        }

        plan = dc.multi_round_plan(
            ownership=self.OWNERSHIP,
            user_roster_id=1,
            current_pick_no=2,
            available={},
            players=self.PLAYERS,
            fc_by_sleeper_id=self.FC_BY_ID,
            user_roster=user_roster,
            league=self.LEAGUE,
            byes={},
            handcuffs={},
            real_picks_by_overall=self.REAL_PICKS_BY_OVERALL,
            draft_snapshot=draft_snapshot,
        )

        round1 = plan["rounds"].iloc[0]
        assert round1["drop_status"] == "confirmed"
        assert round1["drop_name"] == "Filler"
        # Filler (100) outvalues Old WR (50) for the one real WR slot -
        # Taxi Stud (500) is ineligible to start at all, so it must not
        # displace Filler from pre_round_starters.
        assert bool(round1["drop_is_starter"]) is True
