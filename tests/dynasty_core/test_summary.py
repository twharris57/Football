"""Tests for dynasty_core.summary."""

from __future__ import annotations

import pandas as pd

import dynasty_core as dc

EMPTY_WEEKLY_GAPS = pd.DataFrame(
    [{"week": w, "QB": 1, "RB": 2, "WR": 2, "TE": 1, "gap": ""} for w in range(1, 19)]
)
EMPTY_SELLABLE = pd.DataFrame(columns=["player_id", "name", "pos", "age", "value", "adj_value", "position_vor"])
EMPTY_FREE_AGENTS = pd.DataFrame(columns=["name", "pos", "team", "marginal_value", "drop_name", "drop_is_starter"])


def _gap_row(week: int, gap: str) -> dict:
    return {"week": week, "QB": 1, "RB": 2, "WR": 2, "TE": 1, "gap": gap}


def _sellable_row(name: str, pos: str, value: float, adj_value: float) -> dict:
    return {
        "player_id": name.lower().replace(" ", "_"),
        "name": name,
        "pos": pos,
        "age": 25,
        "value": value,
        "adj_value": adj_value,
        "position_vor": 10.0,
    }


def _fa_row(name: str, pos: str, marginal_value: float, drop_name: str | None = None, drop_is_starter=None) -> dict:
    return {
        "name": name,
        "pos": pos,
        "team": "AAA",
        "marginal_value": marginal_value,
        "drop_name": drop_name,
        "drop_is_starter": drop_is_starter,
    }


class TestBuildAttentionDigest:
    def test_empty_inputs_produce_all_empty_lists(self):
        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, EMPTY_SELLABLE, EMPTY_FREE_AGENTS)

        assert digest == {"needs": [], "weekly_gaps": [], "sellable": [], "free_agents": []}

    def test_free_agent_board_with_no_columns_at_all_does_not_crash(self):
        # free_agent_board() returns a columnless pd.DataFrame([]) (not just
        # zero rows of the real columns) when its ranked pool is empty -
        # filtering by column name on that would raise KeyError rather than
        # just finding nothing.
        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, EMPTY_SELLABLE, pd.DataFrame([]))

        assert digest["free_agents"] == []

    def test_needs_combines_positions_into_one_alphabetically_sorted_line(self):
        digest = dc.build_attention_digest(
            frozenset({"WR", "QB"}), EMPTY_WEEKLY_GAPS, EMPTY_SELLABLE, EMPTY_FREE_AGENTS
        )

        assert digest["needs"] == ["Flagged needs: QB, WR"]

    def test_weekly_gaps_lists_only_weeks_with_a_real_gap(self):
        gaps = pd.DataFrame([_gap_row(1, ""), _gap_row(2, "RB"), _gap_row(3, "")])

        digest = dc.build_attention_digest(frozenset(), gaps, EMPTY_SELLABLE, EMPTY_FREE_AGENTS)

        assert digest["weekly_gaps"] == ["Week 2: gap at RB"]

    def test_weekly_gaps_caps_at_top_n_with_a_more_note(self):
        gaps = pd.DataFrame([_gap_row(w, "RB") for w in range(1, 6)])  # 5 gap weeks

        digest = dc.build_attention_digest(frozenset(), gaps, EMPTY_SELLABLE, EMPTY_FREE_AGENTS, top_n=3)

        assert digest["weekly_gaps"] == [
            "Week 1: gap at RB",
            "Week 2: gap at RB",
            "Week 3: gap at RB",
            "(+2 more)",
        ]

    def test_sellable_uses_adj_value_not_the_raw_value_column(self):
        sellable = pd.DataFrame([_sellable_row("Depth WR", "WR", value=999.0, adj_value=42.0)])

        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, sellable, EMPTY_FREE_AGENTS)

        assert digest["sellable"] == ["Depth WR (WR, value: 42)"]

    def test_sellable_shows_unknown_when_adj_value_is_missing(self):
        sellable = pd.DataFrame([_sellable_row("Unmatched WR", "WR", value=100.0, adj_value=None)])

        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, sellable, EMPTY_FREE_AGENTS)

        assert digest["sellable"] == ["Unmatched WR (WR, value: unknown)"]

    def test_sellable_caps_at_top_n_with_a_more_note(self):
        sellable = pd.DataFrame([_sellable_row(f"WR {i}", "WR", value=100.0, adj_value=100.0 - i) for i in range(5)])

        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, sellable, EMPTY_FREE_AGENTS, top_n=3)

        assert digest["sellable"][-1] == "(+2 more)"
        assert len(digest["sellable"]) == 4

    def test_free_agents_filters_to_positive_marginal_value_only(self):
        board = pd.DataFrame(
            [
                _fa_row("Good Add", "RB", marginal_value=15.5),
                _fa_row("No Help", "WR", marginal_value=0.0),
                _fa_row("Actively Bad", "TE", marginal_value=-3.0),
            ]
        )

        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, EMPTY_SELLABLE, board)

        assert digest["free_agents"] == ["Good Add (RB) would add +15.5 to your lineup"]

    def test_free_agents_all_non_positive_returns_empty_list(self):
        board = pd.DataFrame([_fa_row("No Help", "WR", marginal_value=0.0), _fa_row("Bad", "TE", marginal_value=-3.0)])

        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, EMPTY_SELLABLE, board)

        assert digest["free_agents"] == []

    def test_free_agents_notes_a_required_drop_and_whether_its_a_starter(self):
        board = pd.DataFrame(
            [
                _fa_row("Free Add", "RB", marginal_value=10.0),  # no drop needed
                _fa_row("Bench Cost", "WR", marginal_value=8.0, drop_name="Depth WR", drop_is_starter=False),
                _fa_row("Starter Cost", "TE", marginal_value=6.0, drop_name="Starter TE", drop_is_starter=True),
            ]
        )

        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, EMPTY_SELLABLE, board)

        assert digest["free_agents"] == [
            "Free Add (RB) would add +10.0 to your lineup",
            "Bench Cost (WR) would add +8.0 to your lineup — would require dropping Depth WR",
            "Starter Cost (TE) would add +6.0 to your lineup — would require dropping Starter TE (a starter)",
        ]

    def test_free_agents_caps_at_top_n_with_a_more_note(self):
        board = pd.DataFrame([_fa_row(f"Add {i}", "RB", marginal_value=10.0 - i) for i in range(5)])

        digest = dc.build_attention_digest(frozenset(), EMPTY_WEEKLY_GAPS, EMPTY_SELLABLE, board, top_n=3)

        assert digest["free_agents"][-1] == "(+2 more)"
        assert len(digest["free_agents"]) == 4
