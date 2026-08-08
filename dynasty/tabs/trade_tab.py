"""Trade Evaluator tab: manual two-sided trade evaluation plus the trade-target optimizer."""

from __future__ import annotations

import dynasty_core
import pandas as pd
import streamlit as st

from .components import format_drop, team_selectbox


def _trade_player_options(roster: dict, players: dict) -> list[str]:
    return [
        pid
        for pid in (roster.get("players") or [])
        if players.get(pid, {}).get("position") in dynasty_core.FANTASY_POSITIONS
    ]


def _trade_player_label(pid: str, players: dict, fc_by_sleeper_id: dict) -> str:
    info = players.get(pid, {})
    entry = fc_by_sleeper_id.get(pid)
    value = entry.get("adj_value") if entry else None
    value_str = f"{value:.0f}" if bool(pd.notna(value)) else "unknown"
    return f"{info.get('full_name')} ({info.get('position')}, value: {value_str})"


def _trade_pick_options(roster_id: int, pick_values: pd.DataFrame) -> list[str]:
    return list(pick_values.loc[pick_values["owner_roster_id"] == roster_id, "pick"])


def _trade_pick_label(pick_name: str, pick_value_by_name: dict) -> str:
    value = pick_value_by_name.get(pick_name)
    return f"{pick_name} (value: {value:.0f})" if bool(pd.notna(value)) else f"{pick_name} (value: unknown)"


def _combo_asset_label(asset: dict, players: dict) -> str:
    """Render one find_trade_offers() combo asset - same "Name (POS, value: X)"/
    "Pick (value: X)" style _trade_player_label()/_trade_pick_label() use for the
    target, so a suggested offer's give side reads consistently with its receive side."""
    value_str = f"{asset['value']:.0f}" if bool(pd.notna(asset["value"])) else "unknown"
    if asset["kind"] == "player":
        position = players.get(asset["id"], {}).get("position")
        return f"{asset['label']} ({position}, value: {value_str})"
    return f"{asset['label']} (value: {value_str})"


def _show_trade_side(label: str, result: dict) -> None:
    st.markdown(f"**{label}**")
    drops = result["recommended_drops"]
    st.metric(
        "Lineup value",
        f"{result['lineup_delta_after_drops']:+.1f}",
        help=(
            f"Before any forced cuts: {result['lineup_delta']:+.1f}. "
            "Differs when a required drop was an actual starter, not just bench depth."
            if drops
            else None
        ),
    )
    st.metric("Asset value", f"{result['asset_value_delta']:+.1f}")
    if result["over_capacity"]:
        drop_list = ", ".join(format_drop(d) for d in drops)
        st.warning(
            f"Over roster capacity ({result['roster_size_after']}/{result['capacity']}) — "
            f"recommended cut{'s' if len(drops) != 1 else ''}: {drop_list or 'none available'}."
        )
    for callout in result["callouts"]:
        st.caption(f"💡 {callout}")


def _render_manual_evaluator(
    state: dict,
    trade_team_names: dict[int, str],
    your_team_id: int,
    partner_team_id: int,
    your_trade_roster: dict,
    partner_trade_roster: dict,
    trade_players: dict,
    trade_pick_values: pd.DataFrame,
    pick_value_by_name: dict,
) -> None:
    with st.expander("How this works"):
        st.caption(
            "Two independent reads for a proposed trade, not one blended verdict — a trade "
            "can be lineup-critical but value-negative, or value-positive but just adds bench "
            "depth behind an already-strong position.\n"
            "- **Lineup value** — season-average optimal starting-lineup value before vs. "
            "after the trade, the same simulation the Draft Plan uses. If the trade leaves a "
            "roster over capacity, this is the value *after* the recommended cut(s) below, "
            "not the raw trade alone — hover the number to see the raw figure too.\n"
            "- **Asset value** — Adj. Value (players) plus pick value (picks) summed on each "
            "side, FantasyCalc's market read of who gave up more.\n"
            "- **Recommended cuts** — shown when a side goes over roster capacity: the "
            "lowest-value bench player(s) forced out, same heuristic the Draft Plan/Free "
            "agents board use elsewhere. Never recommends cutting a player from the same "
            "trade's incoming side.\n"
            "- **💡 callouts** — non-obvious value the two numbers above can miss: a weekly "
            "bye-week gap this trade opens or closes, an incoming player who handcuffs one of "
            "this side's own current RBs, an outgoing player who wasn't even starting here (a "
            "low real cost to give up) or an incoming one who'd start immediately, and where an "
            "involved pick ranks within its own class. All composed from the same signals used "
            "elsewhere in the app — no separate scoring model.\n"
            "- Shown for both sides — is this good for you, and is it something the partner "
            "would actually want.\n"
            "- 3-way trades aren't supported. Taxi-squad eligibility isn't modeled for "
            "incoming players (same simplification as the Free agents board) — a candidate "
            "is only ever assumed to need an open active roster spot or a drop, not an open "
            "taxi slot. A pick with no resolvable value (a FantasyCalc pick-naming-convention "
            "gap, same one the Draft pick trade values table can hit) contributes 0 to that "
            "side's asset value, noted below if it happens."
        )

    give_col, receive_col = st.columns(2)
    with give_col:
        outgoing_players = st.multiselect(
            "Players you'd give up",
            _trade_player_options(your_trade_roster, trade_players),
            format_func=lambda pid: _trade_player_label(pid, trade_players, state["fc_by_sleeper_id"]),
            key="trade_outgoing_players",
        )
        outgoing_picks = st.multiselect(
            "Picks you'd give up",
            _trade_pick_options(your_team_id, trade_pick_values),
            format_func=lambda pick_name: _trade_pick_label(pick_name, pick_value_by_name),
            key="trade_outgoing_picks",
        )
    with receive_col:
        incoming_players = st.multiselect(
            "Players you'd receive",
            _trade_player_options(partner_trade_roster, trade_players),
            format_func=lambda pid: _trade_player_label(pid, trade_players, state["fc_by_sleeper_id"]),
            key="trade_incoming_players",
        )
        incoming_picks = st.multiselect(
            "Picks you'd receive",
            _trade_pick_options(partner_team_id, trade_pick_values),
            format_func=lambda pick_name: _trade_pick_label(pick_name, pick_value_by_name),
            key="trade_incoming_picks",
        )

    outgoing_pick_value = sum(
        pick_value_by_name.get(p) or 0 for p in outgoing_picks if bool(pd.notna(pick_value_by_name.get(p)))
    )
    incoming_pick_value = sum(
        pick_value_by_name.get(p) or 0 for p in incoming_picks if bool(pd.notna(pick_value_by_name.get(p)))
    )
    unresolved_picks = [p for p in outgoing_picks + incoming_picks if bool(pd.isna(pick_value_by_name.get(p)))]
    if unresolved_picks:
        st.caption(f"No resolvable value for: {', '.join(unresolved_picks)} — contributing 0 to that side's asset value.")

    if not (outgoing_players or outgoing_picks or incoming_players or incoming_picks):
        st.write("(select at least one asset on either side to evaluate a trade)")
        return

    your_result = dynasty_core.evaluate_trade(
        your_trade_roster,
        outgoing_players,
        incoming_players,
        trade_players,
        state["fc_by_sleeper_id"],
        state["byes"],
        state["league"],
        outgoing_pick_value=outgoing_pick_value,
        incoming_pick_value=incoming_pick_value,
        handcuffs=state["handcuffs"],
        outgoing_pick_names=outgoing_picks,
        incoming_pick_names=incoming_picks,
        pick_value_table=trade_pick_values,
    )
    partner_result = dynasty_core.evaluate_trade(
        partner_trade_roster,
        incoming_players,
        outgoing_players,
        trade_players,
        state["fc_by_sleeper_id"],
        state["byes"],
        state["league"],
        outgoing_pick_value=incoming_pick_value,
        incoming_pick_value=outgoing_pick_value,
        handcuffs=state["handcuffs"],
        outgoing_pick_names=incoming_picks,
        incoming_pick_names=outgoing_picks,
        pick_value_table=trade_pick_values,
    )

    your_side_col, partner_side_col = st.columns(2)
    with your_side_col:
        _show_trade_side("Your side", your_result)
    with partner_side_col:
        _show_trade_side(f"{trade_team_names[partner_team_id]}'s side", partner_result)


def _render_trade_optimizer(
    state: dict,
    partner_name: str,
    partner_team_id: int,
    your_trade_roster: dict,
    partner_trade_roster: dict,
    trade_players: dict,
    trade_pick_values: pd.DataFrame,
    pick_value_by_name: dict,
) -> None:
    st.divider()
    st.subheader("Trade-target optimizer")
    with st.expander("How this works"):
        st.caption(
            "Given one specific asset on the trade partner's roster, decide whether it's "
            "worth pursuing and search your own sellable depth/picks for a combination they'd "
            "plausibly accept.\n"
            "- **Worth pursuing** — the same season-average marginal-lineup read as elsewhere, "
            "for acquiring this one asset for free, shown alongside its market value.\n"
            "- **Offer search** — every combination (up to 3 assets) of your own sellable "
            "players/picks, verified two-sided through the same evaluate_trade() check as the "
            "evaluator above — not a new valuation model. A combo only surfaces if the "
            "partner's own asset-value read doesn't come out too lopsided against them (the "
            "real plausibility bar, not just 'cheap for you'); combos that also touch a "
            "flagged need on the partner's roster today are preferred among otherwise-similar "
            "options. Capped to your top 12 highest-value sellable assets so this stays fast.\n"
            "- **💡 callouts** — same non-obvious-value signals as the evaluator above (bye-gap, "
            "handcuffs, buried-bench/instant-starter, pick-in-class ranking), shown per side.\n"
            "- If nothing clears the partner's bar, this says so directly instead of forcing a "
            "marginal offer."
        )

    target_kind = st.radio("Target type", ["Player", "Pick"], key="optimizer_target_kind", horizontal=True)
    target_player_id = target_pick_name = None
    if target_kind == "Player":
        partner_player_options = _trade_player_options(partner_trade_roster, trade_players)
        if not partner_player_options:
            st.write(f"{partner_name} has no fantasy-relevant players to target.")
        else:
            target_player_id = st.selectbox(
                f"Asset on {partner_name}'s roster",
                partner_player_options,
                format_func=lambda pid: _trade_player_label(pid, trade_players, state["fc_by_sleeper_id"]),
                key="optimizer_target_player",
            )
    else:
        partner_pick_options = _trade_pick_options(partner_team_id, trade_pick_values)
        if not partner_pick_options:
            st.write(f"{partner_name} has no tracked picks to target.")
        else:
            target_pick_name = st.selectbox(
                f"Pick owned by {partner_name}",
                partner_pick_options,
                format_func=lambda pick_name: _trade_pick_label(pick_name, pick_value_by_name),
                key="optimizer_target_pick",
            )

    if not (target_player_id or target_pick_name):
        return

    target_label = (
        _trade_player_label(target_player_id, trade_players, state["fc_by_sleeper_id"])
        if target_player_id
        else _trade_pick_label(target_pick_name, pick_value_by_name)
    )
    with st.spinner("Searching for offers..."):
        offer_result = dynasty_core.find_trade_offers(
            your_trade_roster,
            partner_trade_roster,
            trade_players,
            state["fc_by_sleeper_id"],
            state["byes"],
            state["league"],
            state["replacement_level"],
            trade_pick_values,
            handcuffs=state["handcuffs"],
            target_player_id=target_player_id,
            target_pick_name=target_pick_name,
        )

    _show_trade_side(f"If you acquired {target_label} for free", offer_result["target_read"])

    st.markdown("**Suggested offers**")
    offers = offer_result["offers"]
    if not offer_result["target_value_resolved"]:
        st.warning(
            f"No resolvable market value for {target_label} — can't search for a plausible offer "
            "without a value to match against. The lineup-value read above is still valid."
        )
    elif not offers:
        st.info(
            f"No combination of your sellable players/picks clears {partner_name}'s "
            f"plausibility bar for {target_label} — nothing to suggest. Considered "
            f"{offer_result['combos_evaluated']} combinations within a plausible value range."
        )
    else:
        for i, offer in enumerate(offers):
            combo_label = ", ".join(_combo_asset_label(a, trade_players) for a in offer["combo"])
            title = f"{'Best offer' if i == 0 else f'Alternative {i}'}: give {combo_label} → receive {target_label}"
            with st.expander(title, expanded=(i == 0)):
                st.caption(f"**You give:** {combo_label}  \n**You receive:** {target_label}")
                off_col1, off_col2 = st.columns(2)
                with off_col1:
                    _show_trade_side("Your side", offer["your_side"])
                with off_col2:
                    _show_trade_side(f"{partner_name}'s side", offer["partner_side"])
                if offer["partner_need_match"]:
                    positions = ", ".join(sorted(offer["partner_need_positions"]))
                    st.caption(f"Also addresses a flagged need at {positions} on {partner_name}'s roster.")


def render_trade_tab(state: dict) -> None:
    trade_team_names = state["team_names"]
    trade_user_roster_id = state["user_roster_id"]

    your_team_id = team_selectbox(
        "Your team", trade_team_names, trade_user_roster_id, "trade_your_team_select"
    )
    partner_team_id = team_selectbox(
        "Trade partner",
        trade_team_names,
        trade_user_roster_id,
        "trade_partner_team_select",
        exclude=your_team_id,
        tag_you=False,
    )

    your_trade_roster = state["rosters_by_id"][your_team_id]
    partner_trade_roster = state["rosters_by_id"][partner_team_id]
    trade_players = state["players"]
    trade_pick_values = state["pick_trade_values"]
    pick_value_by_name = dict(zip(trade_pick_values["pick"], trade_pick_values["value"]))

    _render_manual_evaluator(
        state,
        trade_team_names,
        your_team_id,
        partner_team_id,
        your_trade_roster,
        partner_trade_roster,
        trade_players,
        trade_pick_values,
        pick_value_by_name,
    )
    _render_trade_optimizer(
        state,
        trade_team_names[partner_team_id],
        partner_team_id,
        your_trade_roster,
        partner_trade_roster,
        trade_players,
        trade_pick_values,
        pick_value_by_name,
    )
