"""Tests for dynasty_core.picks."""

from __future__ import annotations

import pytest

import dynasty_core as dc


class TestTeamNameByRosterId:
    """Team display names should surface which real person is behind a team,
    not just their team's custom name - important for trade context specifically."""

    def test_combines_team_name_and_username_when_both_exist(self):
        rosters = [{"roster_id": 1, "owner_id": "u1"}]
        users = [{"user_id": "u1", "display_name": "bob", "metadata": {"team_name": "My Epic Team Name"}}]

        names = dc.team_name_by_roster_id(rosters, users)

        assert names[1] == "My Epic Team Name (bob)"

    def test_falls_back_to_username_alone_when_no_team_name_set(self):
        rosters = [{"roster_id": 1, "owner_id": "u1"}]
        users = [{"user_id": "u1", "display_name": "bob", "metadata": {}}]

        names = dc.team_name_by_roster_id(rosters, users)

        assert names[1] == "bob"

    def test_falls_back_to_synthetic_label_when_no_user_matched(self):
        rosters = [{"roster_id": 1, "owner_id": "missing"}]
        users = []

        names = dc.team_name_by_roster_id(rosters, users)

        assert names[1] == "Roster 1"


class TestComputePickOwnership:
    """The overall-pick math assumes a linear draft; a different type must fail loudly, not silently."""

    def test_raises_for_a_non_linear_draft_type(self):
        draft = {"type": "snake", "settings": {"teams": 2, "rounds": 1}, "slot_to_roster_id": {"1": 1, "2": 2}}

        with pytest.raises(ValueError, match="linear"):
            dc.compute_pick_ownership(draft, [], "2026")

    def test_linear_draft_keeps_the_same_slot_order_every_round(self):
        draft = {"type": "linear", "settings": {"teams": 2, "rounds": 2}, "slot_to_roster_id": {"1": 1, "2": 2}}

        picks = dc.compute_pick_ownership(draft, [], "2026")

        assert [p.original_roster_id for p in picks] == [1, 2, 1, 2]


class TestPickTradeValues:
    """Remaining current-season picks get their real slot value and owner;
    next season's picks use the flat, non-tiered round value applied to
    every team, since there's no real draft order for a season that hasn't
    happened yet."""

    def test_matches_remaining_current_season_picks_by_exact_slot_name_and_owner(self):
        ownership = [
            dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=1),
            dc.DraftPickSlot(round=1, overall_pick=2, original_roster_id=2, owner_roster_id=2),
        ]
        fc_values = [
            {"player": {"name": "2026 Pick 1.01", "position": "PICK"}, "value": 7000},
            {"player": {"name": "2026 Pick 1.02", "position": "PICK"}, "value": 4000},
        ]
        team_names = {1: "Team One", 2: "Team Two"}

        picks = dc.pick_trade_values(
            ownership,
            current_pick_no=2,
            traded_picks=[],
            num_teams=2,
            num_rounds=1,
            season="2026",
            fc_values=fc_values,
            team_names=team_names,
        )

        current_season = picks[picks["pick"].str.startswith("2026")]
        # Pick 1.01 already happened (overall_pick 1 < current_pick_no 2) - excluded.
        assert list(current_season["pick"]) == ["2026 Pick 1.02"]
        assert current_season.iloc[0]["owner"] == "Team Two"
        assert current_season.iloc[0]["value"] == pytest.approx(4000)

    def test_traded_pick_is_owned_by_the_new_owner_in_ownership_input(self):
        # owner_roster_id already reflects the trade - that's
        # compute_pick_ownership's job upstream, this just confirms
        # pick_trade_values passes it through rather than the original owner.
        ownership = [dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=2)]
        fc_values = [{"player": {"name": "2026 Pick 1.01", "position": "PICK"}, "value": 7000}]
        team_names = {1: "Original Team", 2: "New Owner"}

        picks = dc.pick_trade_values(
            ownership,
            current_pick_no=1,
            traded_picks=[],
            num_teams=1,
            num_rounds=1,
            season="2026",
            fc_values=fc_values,
            team_names=team_names,
        )

        assert picks.iloc[0]["owner"] == "New Owner"
        assert picks.iloc[0]["owner_roster_id"] == 2

    def test_next_season_uses_the_flat_non_tiered_round_value_for_every_team(self):
        team_names = {1: "Team One", 2: "Team Two"}
        fc_values = [
            {"player": {"name": "2027 1st", "position": "PICK"}, "value": 2500},
            {"player": {"name": "2027 1st (Early)", "position": "PICK"}, "value": 4000},
        ]

        picks = dc.pick_trade_values(
            ownership=[],
            current_pick_no=1,
            traded_picks=[],
            num_teams=2,
            num_rounds=1,
            season="2026",
            fc_values=fc_values,
            team_names=team_names,
        )

        next_season = picks[picks["pick"] == "2027 1st"]
        # Every team's future 1st uses the same flat value - not the tiered
        # "(Early)" bucket, which would require guessing a team's future
        # standing this far out.
        assert len(next_season) == 2
        assert set(next_season["value"]) == {2500.0}

    def test_traded_future_pick_is_owned_by_the_new_owner(self):
        team_names = {1: "Team One", 2: "Team Two"}
        traded_picks = [{"round": 1, "season": "2027", "roster_id": 1, "owner_id": 2}]
        fc_values = [{"player": {"name": "2027 1st", "position": "PICK"}, "value": 2500}]

        picks = dc.pick_trade_values(
            ownership=[],
            current_pick_no=1,
            traded_picks=traded_picks,
            num_teams=2,
            num_rounds=1,
            season="2026",
            fc_values=fc_values,
            team_names=team_names,
        )

        # Roster 1's own future pick was traded away - roster 2 now owns
        # both its own pick and the traded-in one; roster 1 owns neither.
        assert len(picks[picks["owner_roster_id"] == 1]) == 0
        assert len(picks[picks["owner_roster_id"] == 2]) == 2

    def test_unmatched_pick_names_leave_value_empty_not_an_error(self):
        # A FantasyCalc pick-naming convention change is exactly the
        # silent-failure mode this join is exposed to (name-string match,
        # no other stable join key for picks) - it must degrade to an
        # empty value column, not raise, so gather_state's own
        # all-NaN check (see PROJECT_PLAN_DYNASTY.md's "Current branch" review
        # findings) has something real to detect.
        ownership = [dc.DraftPickSlot(round=1, overall_pick=1, original_roster_id=1, owner_roster_id=1)]
        fc_values = [{"player": {"name": "totally different naming scheme", "position": "PICK"}, "value": 7000}]
        team_names = {1: "Team One"}

        picks = dc.pick_trade_values(
            ownership,
            current_pick_no=1,
            traded_picks=[],
            num_teams=1,
            num_rounds=1,
            season="2026",
            fc_values=fc_values,
            team_names=team_names,
        )

        assert picks["value"].isna().all()
