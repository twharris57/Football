"""Tests for dynasty_core.waiver_bids."""

from __future__ import annotations

import pandas as pd

import dynasty_core as dc
from tests.dynasty_core.helpers import fc_entry, make_player


def _waiver_txn(status: str, player_id: str, bid: float | None) -> dict:
    return {
        "type": "waiver",
        "status": status,
        "settings": {"waiver_bid": bid} if bid is not None else {},
        "adds": {player_id: 1},
    }


class TestWonBidSample:
    def test_only_complete_waiver_transactions_are_counted(self):
        players = {"a": make_player("WR"), "b": make_player("RB")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a", 100, position="WR"), fc_entry("b", 50, position="RB")])
        transactions = [
            _waiver_txn("complete", "a", 15),
            _waiver_txn("failed", "b", 20),  # never won - excluded
            {"type": "trade", "status": "complete", "adds": {"a": 1}, "settings": {}},  # not a waiver - excluded
        ]

        sample = dc.won_bid_sample(transactions, players, fc_by_id)

        assert list(sample["player_id"]) == ["a"]
        assert list(sample["bid"]) == [15]

    def test_resolves_position_and_current_adj_value(self):
        players = {"a": make_player("WR")}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a", 200, position="WR")])
        transactions = [_waiver_txn("complete", "a", 30)]

        sample = dc.won_bid_sample(transactions, players, fc_by_id)

        assert sample.iloc[0]["position"] == "WR"
        assert sample.iloc[0]["adj_value"] > 0

    def test_player_with_no_resolvable_value_is_excluded(self):
        players = {"a": make_player("WR")}
        fc_by_id: dict = {}  # no FantasyCalc entry at all for "a"
        transactions = [_waiver_txn("complete", "a", 10)]

        sample = dc.won_bid_sample(transactions, players, fc_by_id)

        assert sample.empty

    def test_non_fantasy_position_is_excluded(self):
        players = {"a": {"position": "DEF", "team": "AAA", "full_name": "Defense"}}
        fc_by_id = dc.fc_value_by_sleeper_id([fc_entry("a", 10, position="DEF")])
        transactions = [_waiver_txn("complete", "a", 5)]

        sample = dc.won_bid_sample(transactions, players, fc_by_id)

        assert sample.empty

    def test_empty_input_returns_empty_columned_dataframe(self):
        sample = dc.won_bid_sample([], {}, {})

        assert sample.empty
        assert list(sample.columns) == ["player_id", "position", "adj_value", "bid"]


class TestNearestComparableBids:
    def _sample(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"player_id": "wr1", "position": "WR", "adj_value": 100.0, "bid": 10.0},
                {"player_id": "wr2", "position": "WR", "adj_value": 110.0, "bid": 12.0},
                {"player_id": "wr3", "position": "WR", "adj_value": 90.0, "bid": 8.0},
                {"player_id": "rb1", "position": "RB", "adj_value": 105.0, "bid": 50.0},
            ]
        )

    def test_prefers_same_position_when_sample_is_large_enough(self):
        comparables, same_position = dc.nearest_comparable_bids(100.0, "WR", self._sample(), min_same_position=3)

        assert same_position is True
        assert {c["bid"] for c in comparables} == {10.0, 12.0, 8.0}  # the 3 WR rows only, RB excluded

    def test_broadens_to_all_positions_when_same_position_sample_is_too_thin(self):
        sample = self._sample()
        comparables, same_position = dc.nearest_comparable_bids(100.0, "TE", sample, min_same_position=3)

        assert same_position is False
        assert 50.0 in {c["bid"] for c in comparables}  # the RB row is now eligible since no TE rows exist at all

    def test_qb_never_broadens_even_when_same_position_sample_is_too_thin(self):
        # Superflex scarcity means a QB bid isn't comparable to a same-value
        # RB/WR/TE bid - QB should stay on its own thin pool (empty here)
        # rather than broadening into the WR/RB rows, per RT-28.
        sample = self._sample()  # no QB rows at all

        comparables, same_position = dc.nearest_comparable_bids(100.0, "QB", sample, min_same_position=3)

        assert comparables == []
        assert same_position is True

    def test_qb_stays_on_its_own_thin_sample_instead_of_the_broadened_pool(self):
        sample = pd.concat(
            [self._sample(), pd.DataFrame([{"player_id": "qb1", "position": "QB", "adj_value": 100.0, "bid": 40.0}])],
            ignore_index=True,
        )

        comparables, same_position = dc.nearest_comparable_bids(100.0, "QB", sample, min_same_position=3)

        assert same_position is True
        assert {c["bid"] for c in comparables} == {40.0}  # only the 1 real QB row, never the WR/RB rows

    def test_returns_genuinely_nearest_by_value_not_just_first_k(self):
        sample = pd.DataFrame(
            [
                {"player_id": p, "position": "WR", "adj_value": v, "bid": v}
                for p, v in [("far1", 500.0), ("near1", 101.0), ("far2", 5.0), ("near2", 99.0)]
            ]
        )

        comparables, _ = dc.nearest_comparable_bids(100.0, "WR", sample, k=2)

        assert {c["bid"] for c in comparables} == {101.0, 99.0}

    def test_each_comparable_carries_its_own_adj_value_alongside_its_bid(self):
        comparables, _ = dc.nearest_comparable_bids(100.0, "WR", self._sample(), min_same_position=3)

        by_bid = {c["bid"]: c["adj_value"] for c in comparables}
        assert by_bid[10.0] == 100.0
        assert by_bid[12.0] == 110.0
        assert by_bid[8.0] == 90.0

    def test_excludes_comparables_too_far_in_value_even_though_the_pool_is_nonempty(self):
        # Same-position count clears min_same_position, so the pool selection
        # itself succeeds - but every row is a wildly different tier of
        # player than the candidate, so none should count as "comparable."
        sample = self._sample()

        comparables, same_position = dc.nearest_comparable_bids(2000.0, "WR", sample, min_same_position=3)

        assert comparables == []
        assert same_position is True

    def test_empty_sample_returns_no_bids(self):
        comparables, same_position = dc.nearest_comparable_bids(
            100.0, "WR", pd.DataFrame(columns=["position", "adj_value", "bid"])
        )

        assert comparables == []


class TestBidGuidance:
    def test_returns_none_below_min_comparable_sample(self):
        sample = pd.DataFrame(
            [
                {"player_id": "wr1", "position": "WR", "adj_value": 100.0, "bid": 10.0},
                {"player_id": "wr2", "position": "WR", "adj_value": 110.0, "bid": 12.0},
            ]
        )  # only 2 - below MIN_COMPARABLE_SAMPLE (3)

        assert dc.bid_guidance(100.0, "WR", sample) is None

    def test_computes_low_median_high_from_the_exact_comparable_list(self):
        sample = pd.DataFrame(
            [
                {"player_id": "wr1", "position": "WR", "adj_value": 100.0, "bid": 10.0},
                {"player_id": "wr2", "position": "WR", "adj_value": 101.0, "bid": 20.0},
                {"player_id": "wr3", "position": "WR", "adj_value": 99.0, "bid": 30.0},
            ]
        )

        guidance = dc.bid_guidance(100.0, "WR", sample)

        assert [c["bid"] for c in guidance["comparables"]] == [10.0, 20.0, 30.0]
        assert guidance["low"] == 10.0
        assert guidance["median"] == 20.0
        assert guidance["high"] == 30.0
        assert guidance["same_position"] is True

    def test_returns_none_when_comparables_exist_but_are_all_too_far_in_value(self):
        # 3 real comparables clear MIN_COMPARABLE_SAMPLE on count alone, but
        # the candidate is a far higher tier of player than any of them -
        # a count floor with no distance floor would wrongly show guidance here.
        sample = pd.DataFrame(
            [
                {"player_id": "wr1", "position": "WR", "adj_value": 50.0, "bid": 5.0},
                {"player_id": "wr2", "position": "WR", "adj_value": 60.0, "bid": 6.0},
                {"player_id": "wr3", "position": "WR", "adj_value": 70.0, "bid": 7.0},
            ]
        )

        assert dc.bid_guidance(2000.0, "WR", sample) is None

    def test_same_position_flag_reflects_broadening(self):
        sample = pd.DataFrame(
            [
                {"player_id": "rb1", "position": "RB", "adj_value": 100.0, "bid": 10.0},
                {"player_id": "rb2", "position": "RB", "adj_value": 101.0, "bid": 20.0},
                {"player_id": "rb3", "position": "RB", "adj_value": 99.0, "bid": 30.0},
            ]
        )

        guidance = dc.bid_guidance(100.0, "TE", sample)

        assert guidance is not None
        assert guidance["same_position"] is False

    def test_qb_gets_no_guidance_rather_than_a_broadened_range(self):
        # A same-value RB sample clears MIN_COMPARABLE_SAMPLE easily, but a
        # QB candidate should never be shown a range built from non-QB bids
        # (RT-28) - "no guidance yet" is the honest outcome here.
        sample = pd.DataFrame(
            [
                {"player_id": "rb1", "position": "RB", "adj_value": 100.0, "bid": 10.0},
                {"player_id": "rb2", "position": "RB", "adj_value": 101.0, "bid": 20.0},
                {"player_id": "rb3", "position": "RB", "adj_value": 99.0, "bid": 30.0},
            ]
        )

        assert dc.bid_guidance(100.0, "QB", sample) is None
