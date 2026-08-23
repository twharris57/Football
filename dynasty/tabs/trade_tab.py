"""Trade Evaluator tab: manual two-sided trade evaluation plus leaguewide Suggested Trades."""

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


def _leaguewide_owner_by_player_id(rosters_by_id: dict[int, dict], user_roster_id: int, players: dict) -> dict[str, int]:
    """player_id -> roster_id for every fantasy-relevant player on every *other* roster.

    Same fantasy-position filter as `_trade_player_options`, just across
    every roster but the user's own - the pool the Suggested Trades
    section's single-target picker searches, since it isn't scoped to one
    hand-picked partner."""
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
    """RT-14: someone proposed the trade above *to* us. Reuses the exact
    assets already selected in the manual evaluator - no new selectors -
    to either confirm it's worth taking, suggest a nearby adjustment, or
    say plainly that no adjustment found makes it worth taking.

    The result is tagged with a signature of everything it was computed
    from (which teams, which assets, and state["version"]) and dropped on
    a mismatch - the same versioned-on-demand-result pattern
    docs/dynasty-data-model.md documents for Suggested Trades (RT-24), extended
    here to also cover the user's own selection changing, not just a
    refresh. Unlike RT-24, no "data changed" message on invalidation -
    the trigger here is the user's own edit to the selection, not a
    background refresh, so it isn't surprising that the button needs a
    fresh click.
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
            "No adjustment found makes this proposal worth taking — the read above holds "
            "regardless of a small tweak. Consider declining."
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
        # A scan from an earlier refresh - roster/market data has moved on
        # since (another manager's trade, a waiver claim, a fresh Refresh
        # click), so the offers it found are no longer guaranteed valid.
        # Drop it rather than silently keep showing it; the button above is
        # right there to re-scan (see docs/dynasty-data-model.md's "versioned
        # on-demand-result pattern").
        del st.session_state["suggested_trades_results"]
        cached = None
        st.info("Data has changed since your last scan — press “Scan the league for offers” again for current results.")

    results = cached["results"] if cached is not None else None
    if results is None:
        return
    if not results:
        st.info(
            "None of the top leaguewide candidates cleared a partner's plausibility bar right "
            "now — try again after your roster or the market shifts, or search a specific "
            "player directly above."
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
            "Leaguewide by default, not scoped to the 'Your team'/'Trade partner' selectors "
            "above — always scans for your own actual roster, regardless of what's selected "
            "there for the manual evaluator.\n"
            "- **Leaguewide candidates** — every fantasy-relevant player on every other "
            "team's roster, ranked by the same season-average marginal-lineup read used "
            "elsewhere, pre-filtered to ones your own sellable depth could plausibly afford "
            "(a rough ceiling from your top 3 sellable assets' value) so the real search "
            "below isn't spent entirely on unreachable stars. Free to show — already "
            "computed this refresh.\n"
            "- **Scan the league for offers** — the real two-sided search (same "
            "evaluate_trade() check as the manual evaluator above, not a new valuation "
            "model), repeated for the strongest ~15 leaguewide candidates, showing the top 3 "
            "that actually clear a partner's plausibility bar. Ranked primarily by long-run "
            "lineup value (matching a rebuild strategy's multi-season focus), with weekly-gap "
            "impact — the same 💡 signal the manual evaluator's callouts show — as a "
            "secondary tie-break only, never able to outrank a real lineup-value difference. "
            "This is the expensive part, so it's behind a button rather than running on every "
            "page interaction.\n"
            "- **Or search one player directly** — pick anyone on another team's roster to "
            "search immediately, without a full leaguewide scan or picking a partner first.\n"
            "- Picks aren't targetable in this section yet — draft-pick trades are still "
            "fully supported in the manual evaluator above."
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
    _render_suggested_trades(state)
