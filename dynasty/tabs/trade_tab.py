"""Trade Evaluator tab: manual two-sided trade evaluation plus leaguewide Suggested Trades."""

from __future__ import annotations

import datetime as dt
import sqlite3

import dynasty_core
import pandas as pd
import streamlit as st
import trade_block_store

from .components import format_drop, team_selectbox


def _trade_player_options(roster: dict, players: dict) -> list[str]:
    return [
        pid
        for pid in (roster.get("players") or [])
        if players.get(pid, {}).get("position") in dynasty_core.FANTASY_POSITIONS
    ]


def _leaguewide_owner_by_player_id(rosters_by_id: dict[int, dict], user_roster_id: int, players: dict) -> dict[str, int]:
    """player_id -> roster_id for fantasy-position players on every other roster."""
    owner_by_player_id: dict[str, int] = {}
    for roster_id, roster in rosters_by_id.items():
        if roster_id == user_roster_id:
            continue
        for pid in _trade_player_options(roster, players):
            owner_by_player_id[pid] = roster_id
    return owner_by_player_id


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
    """Label a combo asset in the same style as the target labels."""
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
            f"Before forced cuts: {result['lineup_delta']:+.1f} (differs when a cut "
            "player was a starter)."
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
            (
                'Two separate reads per side, not one verdict:\n- **Lineup value** — '
                'season-average starting lineup before vs. after, including any forced cuts '
                '(hover for the raw number).\n- **Asset value** — Adj. Value plus pick '
                'value given vs. received.\n- **Recommended cuts** — lowest-value bench '
                'players, if a side goes over capacity. Never an incoming player.\n- **💡 '
                'Callouts** — weekly gaps opened or closed, handcuffs, bench players given '
                'up, instant starters, and pick rank in its class.\n\nNot supported: 3-way '
                'trades, and taxi slots for incoming players. A pick with no FantasyCalc '
                'value counts as 0.'
            )
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

    _render_improve_offer_section(
        state,
        your_team_id,
        partner_team_id,
        your_trade_roster,
        partner_trade_roster,
        trade_team_names[partner_team_id],
        outgoing_players,
        outgoing_picks,
        incoming_players,
        incoming_picks,
        trade_players,
        trade_pick_values,
    )


def _describe_improvement_move(improvement: dict, trade_players: dict) -> str:
    move, side = improvement["move"], improvement["side"]
    removed, added = improvement["removed"], improvement["added"]
    if move == "drop":
        return f"Don't include {_combo_asset_label(removed, trade_players)}"
    if move == "add":
        verb = "Also give" if side == "yours" else "Also ask for"
        return f"{verb} {_combo_asset_label(added, trade_players)}"
    verb = "give" if side == "yours" else "ask for"
    return f"Instead of {_combo_asset_label(removed, trade_players)}, {verb} {_combo_asset_label(added, trade_players)}"


def _render_improvement(improvement: dict, partner_name: str, trade_players: dict, expanded: bool) -> None:
    with st.expander(_describe_improvement_move(improvement, trade_players), expanded=expanded):
        col1, col2 = st.columns(2)
        with col1:
            _show_trade_side("Your side", improvement["your_side"])
        with col2:
            _show_trade_side(f"{partner_name}'s side", improvement["partner_side"])


def _render_improve_offer_section(
    state: dict,
    your_team_id: int,
    partner_team_id: int,
    your_trade_roster: dict,
    partner_trade_roster: dict,
    partner_name: str,
    outgoing_players: list[str],
    outgoing_picks: list[str],
    incoming_players: list[str],
    incoming_picks: list[str],
    trade_players: dict,
    trade_pick_values: pd.DataFrame,
) -> None:
    """Judge the selected trade as an incoming offer: accept, counter, or reject.

    The cached result is tagged with the teams, assets, and state version, and is
    dropped quietly when any of them change.
    """
    current_signature = (
        state["version"],
        your_team_id,
        partner_team_id,
        tuple(sorted(outgoing_players)),
        tuple(sorted(outgoing_picks)),
        tuple(sorted(incoming_players)),
        tuple(sorted(incoming_picks)),
    )

    st.divider()
    if st.button("Suggest an improvement"):
        with st.spinner("Checking for a better version of this trade..."):
            st.session_state["improve_offer_result"] = {
                "signature": current_signature,
                "result": dynasty_core.improve_incoming_offer(
                    your_trade_roster,
                    partner_trade_roster,
                    outgoing_players,
                    outgoing_picks,
                    incoming_players,
                    incoming_picks,
                    trade_players,
                    state["fc_by_sleeper_id"],
                    state["byes"],
                    state["league"],
                    state["replacement_level"],
                    trade_pick_values,
                    handcuffs=state["handcuffs"],
                ),
            }

    cached = st.session_state.get("improve_offer_result")
    if cached is not None and cached["signature"] != current_signature:
        del st.session_state["improve_offer_result"]
        cached = None
    if cached is None:
        return

    result = cached["result"]
    if result["verdict"] == "reject":
        st.error(
            'No tweak makes this worth taking. Consider declining.'
        )
    elif result["verdict"] == "accept":
        st.success("This proposal is already worth taking as-is.")
        if result["improvements"]:
            st.caption("Optional upside — these would make it even better, if the partner's open to it:")
            for improvement in result["improvements"]:
                _render_improvement(improvement, partner_name, trade_players, expanded=False)
    else:
        st.info("Not quite worth it as proposed — here's how to make it work:")
        for i, improvement in enumerate(result["improvements"]):
            _render_improvement(improvement, partner_name, trade_players, expanded=(i == 0))


def _render_offer_body(offer: dict, target_label: str, partner_name: str, trade_players: dict) -> None:
    combo_label = ", ".join(_combo_asset_label(a, trade_players) for a in offer["combo"])
    st.caption(f"**You give:** {combo_label}  \n**You receive:** {target_label}")
    off_col1, off_col2 = st.columns(2)
    with off_col1:
        _show_trade_side("Your side", offer["your_side"])
    with off_col2:
        _show_trade_side(f"{partner_name}'s side", offer["partner_side"])
    if offer["partner_need_match"]:
        positions = ", ".join(sorted(offer["partner_need_positions"]))
        st.caption(f"Also addresses a flagged need at {positions} on {partner_name}'s roster.")


def _render_single_target_search(
    state: dict,
    target_player_id: str,
    partner_roster: dict,
    partner_name: str,
    trade_players: dict,
    trade_pick_values: pd.DataFrame,
) -> None:
    target_label = _trade_player_label(target_player_id, trade_players, state["fc_by_sleeper_id"])
    with st.spinner("Searching for offers..."):
        offer_result = dynasty_core.find_trade_offers(
            state["rosters_by_id"][state["user_roster_id"]],
            partner_roster,
            trade_players,
            state["fc_by_sleeper_id"],
            state["byes"],
            state["league"],
            state["replacement_level"],
            trade_pick_values,
            handcuffs=state["handcuffs"],
            target_player_id=target_player_id,
        )

    _show_trade_side(f"If you acquired {target_label} for free", offer_result["target_read"])

    st.markdown("**Suggested offers**")
    offers = offer_result["offers"]
    if not offer_result["target_value_resolved"]:
        st.warning(
            f"No market value for {target_label}, so there's nothing to match an offer "
            "against. The lineup read above still holds."
        )
    elif not offers:
        st.info(
            f"None of {offer_result['combos_evaluated']} combinations of your sellable "
            f"assets would plausibly get {target_label} from {partner_name}."
        )
    else:
        for i, offer in enumerate(offers):
            combo_label = ", ".join(_combo_asset_label(a, trade_players) for a in offer["combo"])
            title = f"{'Best offer' if i == 0 else f'Alternative {i}'}: give {combo_label} → receive {target_label}"
            with st.expander(title, expanded=(i == 0)):
                _render_offer_body(offer, target_label, partner_name, trade_players)


def _render_leaguewide_scan(state: dict, trade_players: dict, trade_pick_values: pd.DataFrame) -> None:
    candidates = state["suggested_trade_candidates"]
    st.caption(f"{len(candidates)} leaguewide candidate{'s' if len(candidates) != 1 else ''} worth a look right now.")
    if not candidates:
        st.info("No leaguewide candidate cleared the affordability/marginal-value bar this refresh.")
        return

    if st.button("Scan the league for offers"):
        with st.spinner("Scanning the league..."):
            st.session_state["suggested_trades_results"] = {
                "state_version": state["version"],
                "results": dynasty_core.suggested_trades(
                    state["rosters_by_id"][state["user_roster_id"]],
                    state["rosters_by_id"],
                    trade_players,
                    state["fc_by_sleeper_id"],
                    state["byes"],
                    state["league"],
                    state["replacement_level"],
                    trade_pick_values,
                    candidates,
                    handcuffs=state["handcuffs"],
                ),
            }

    cached = st.session_state.get("suggested_trades_results")
    if cached is not None and cached["state_version"] != state["version"]:
        # Computed against an earlier refresh; drop it rather than show stale offers.
        del st.session_state["suggested_trades_results"]
        cached = None
        st.info("Data has changed since your last scan — press “Scan the league for offers” again for current results.")

    results = cached["results"] if cached is not None else None
    if results is None:
        return
    if not results:
        st.info(
            (
                "No offer cleared a partner's bar right now. Try again later, or search a "
                'specific player above.'
            )
        )
        return

    for i, result in enumerate(results):
        partner_name = state["team_names"][result["roster_id"]]
        target_label = _trade_player_label(result["target_player_id"], trade_players, state["fc_by_sleeper_id"])
        best_offer = result["offers"][0]
        combo_label = ", ".join(_combo_asset_label(a, trade_players) for a in best_offer["combo"])
        title = f"#{i + 1}: give {combo_label} → receive {target_label} ({partner_name})"
        with st.expander(title, expanded=(i == 0)):
            _render_offer_body(best_offer, target_label, partner_name, trade_players)


def _render_suggested_trades(state: dict) -> None:
    st.divider()
    st.subheader("Suggested Trades")
    with st.expander("How this works"):
        st.caption(
            (
                'Always scans for your own roster, regardless of the Manual Trade '
                "selections.\n- **Candidates** — other teams' players ranked by lineup "
                'gain, limited to what your sellable depth can afford.\n- **Scan the '
                'league** — searches offers for the top ~15 candidates and shows the best '
                "3, ranked by lineup gain (weekly gaps break ties). Slow, so it's behind a "
                'button.\n- **Search one player** — any player on another roster, right '
                "away.\n\nPicks can't be targeted here; use Manual Trade."
            )
        )

    trade_players = state["players"]
    trade_pick_values = state["pick_trade_values"]
    owner_by_player_id = _leaguewide_owner_by_player_id(state["rosters_by_id"], state["user_roster_id"], trade_players)

    target_player_id = st.selectbox(
        "Or search one specific player instead",
        [None] + sorted(owner_by_player_id, key=lambda pid: trade_players.get(pid, {}).get("full_name") or ""),
        format_func=lambda pid: (
            "(none — show leaguewide suggestions)"
            if pid is None
            else f"{_trade_player_label(pid, trade_players, state['fc_by_sleeper_id'])} "
            f"— {state['team_names'][owner_by_player_id[pid]]}"
        ),
        key="suggested_trades_target_player",
    )

    if target_player_id:
        partner_roster = state["rosters_by_id"][owner_by_player_id[target_player_id]]
        partner_name = state["team_names"][owner_by_player_id[target_player_id]]
        _render_single_target_search(
            state, target_player_id, partner_roster, partner_name, trade_players, trade_pick_values
        )
        return

    _render_leaguewide_scan(state, trade_players, trade_pick_values)


def _trade_block_row_label(sleeper_id: str, players: dict) -> str:
    info = players.get(sleeper_id, {})
    return f"{info.get('full_name')} ({info.get('position')})"


@st.cache_resource(show_spinner=False)
def _get_trade_block_connection() -> sqlite3.Connection:
    """One connection per server process; per-rerun connections race for the write lock."""
    trade_block_store.DATA_DIR.mkdir(parents=True, exist_ok=True)
    return trade_block_store.connect(str(trade_block_store.DB_PATH))


def _render_trade_block(state: dict) -> None:
    with st.expander("How this works"):
        st.caption(
            (
                "Players other managers say they'll trade (Sleeper doesn't track this, so "
                "it's entered here).\n- Removed automatically once the player leaves that "
                "roster (traded or dropped).\n- Adding a player who's already listed does "
                'nothing.'
            )
        )

    conn = _get_trade_block_connection()
    trade_players = state["players"]
    entries = trade_block_store.get_trade_block(conn)

    kept, pruned = dynasty_core.prune_stale_entries(entries, state["rosters_by_id"])
    if pruned:
        for p in pruned:
            trade_block_store.remove_trade_block_entry(conn, p.entry.sleeper_id)
        removed_labels = "; ".join(
            f"{_trade_block_row_label(p.entry.sleeper_id, trade_players)} ({p.reason})" for p in pruned
        )
        st.info(f"Auto-removed (no longer on that roster): {removed_labels}")
        entries = kept

    st.markdown("**Add a player**")
    add_team_id = team_selectbox(
        "Team shopping the player", state["team_names"], state["user_roster_id"], "trade_block_add_team"
    )
    already_blocked = {e.sleeper_id for e in entries}
    add_options = [
        pid for pid in _trade_player_options(state["rosters_by_id"][add_team_id], trade_players)
        if pid not in already_blocked
    ]
    # Keyed per team: Streamlit raises if a persisted value isn't in the current options.
    player_select_key = f"trade_block_add_player_{add_team_id}"
    add_player_id = st.selectbox(
        "Player",
        [None] + sorted(add_options, key=lambda pid: trade_players.get(pid, {}).get("full_name") or ""),
        format_func=lambda pid: "(select a player)" if pid is None else _trade_block_row_label(pid, trade_players),
        key=player_select_key,
    )
    if st.button("Add to trade block", key="trade_block_add_button", disabled=add_player_id is None):
        try:
            trade_block_store.add_trade_block_entry(conn, add_player_id, add_team_id, dt.date.today().isoformat())
        except sqlite3.IntegrityError:
            st.warning("Already on the trade block.")
            # Already listed elsewhere: clear the selection but skip the rerun so the warning stays.
            del st.session_state[player_select_key]
        else:
            # Clear the selection; the added player leaves the options.
            del st.session_state[player_select_key]
            st.rerun()

    st.divider()
    st.markdown("**Currently on the block**")
    if not entries:
        st.write("(nothing on the trade block right now)")
        return

    for roster_id in sorted({e.roster_id for e in entries}, key=lambda rid: state["team_names"].get(rid, "")):
        st.caption(state["team_names"].get(roster_id, f"Roster {roster_id}"))
        roster_entries = sorted(
            (e for e in entries if e.roster_id == roster_id),
            key=lambda e: trade_players.get(e.sleeper_id, {}).get("full_name") or "",
        )
        for entry in roster_entries:
            name_col, date_col, remove_col = st.columns([3, 2, 2])
            with name_col:
                st.write(_trade_block_row_label(entry.sleeper_id, trade_players))
            with date_col:
                st.write(entry.added_date)
            with remove_col:
                # Removal can't be undone, so confirm first.
                confirm_key = f"trade_block_remove_confirm_{entry.sleeper_id}"
                if st.session_state.get(confirm_key):
                    confirm_col, cancel_col = st.columns(2)
                    with confirm_col:
                        if st.button("Confirm", key=f"trade_block_remove_yes_{entry.sleeper_id}", type="primary"):
                            trade_block_store.remove_trade_block_entry(conn, entry.sleeper_id)
                            del st.session_state[confirm_key]
                            st.rerun()
                    with cancel_col:
                        if st.button("Cancel", key=f"trade_block_remove_no_{entry.sleeper_id}"):
                            del st.session_state[confirm_key]
                            st.rerun()
                else:
                    if st.button("Remove", key=f"trade_block_remove_{entry.sleeper_id}"):
                        st.session_state[confirm_key] = True
                        st.rerun()


def render_trade_tab(state: dict) -> None:
    manual_tab, suggested_tab, block_tab = st.tabs(["Manual Trade", "Suggested Trades", "Trade Block"])
    with manual_tab:
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
    with suggested_tab:
        _render_suggested_trades(state)
    with block_tab:
        _render_trade_block(state)
