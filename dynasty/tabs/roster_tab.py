"""Roster tab: per-team needs, value, trade-candidate, and capacity views."""

from __future__ import annotations

import dynasty_core
import pandas as pd
import streamlit as st

from .components import cols, show_df, show_status_table, team_selectbox


def _render_team_timeline(state: dict, selected_roster_id: int) -> None:
    st.subheader("Team timeline")
    with st.expander("How this works"):
        st.caption(
            (
                'Where this team sits between rebuilding and contending, recomputed every '
                'refresh.\n- **Score** — league-relative average of roster strength (VOR), '
                'value-weighted age, and record. 0 is average; positive leans win-now. '
                '**Rank** is the same score as "3 of 12".\n- **Phase** — the score in three '
                'buckets. It also decides what **Need** and **Note** mean below, so check '
                'the raw score when a team is near a boundary.\n- **Win %** shows "no games '
                'played yet" until the season starts.'
            )
        )
    power = state["team_power_timeline"].loc[selected_roster_id]
    league_size = len(state["team_power_timeline"])
    phase_labels = {"rebuilding": "🌱 Rebuilding", "treading_water": "⚖️ Treading water", "contending": "🏆 Contending"}
    phase = str(power["phase"])
    st.metric(
        phase_labels.get(phase, phase),
        f"{int(power['rank'])} of {league_size}",
        help=(
            f"Power score: {power['power_score']:+.2f} (0 = league average; "
            "positive leans contending)."
        ),
    )
    win_pct_text = "no games played yet" if power["games_played"] == 0 else f"{power['win_pct']:.0%}"
    st.caption(
        f"Roster strength (VOR): {power['aggregate_vor']:+.1f} · "
        f"Value-weighted age: {power['weighted_age']:.1f} · "
        f"Win %: {win_pct_text}"
    )


def _render_capacity(analysis: dict) -> None:
    st.subheader("Roster capacity")
    cap = analysis["roster_capacity"]
    cap_col1, cap_col2, cap_col3 = st.columns(3)
    cap_col1.metric("Active roster", f"{cap['active_filled']}/{cap['active_total']}", f"{cap['active_open']} open")
    cap_col2.metric("Taxi squad", f"{cap['taxi_filled']}/{cap['taxi_total']}", f"{cap['taxi_open']} open")
    cap_col3.metric("IR / Reserve", f"{cap['reserve_filled']}/{cap['reserve_total']}", f"{cap['reserve_open']} open")
    if cap["active_open"] <= 0 and cap["taxi_open"] <= 0:
        st.warning("No open roster or taxi slots — drafting a rookie means dropping someone first.")


def _render_needs(analysis: dict) -> None:
    st.subheader("Roster needs")
    with st.expander("How this works"):
        st.caption(
            (
                'Two questions per position:\n- **Need** — while rebuilding: fewer than 2 '
                'players with 2 or fewer years of experience. Otherwise it means the same '
                "as Weak.\n- **Weak** — this team's starters are worth no more than the "
                "league's replacement level (**VOR** ≤ 0), whatever the depth.\n\nVOR "
                'compares against the whole league, so one star elsewhere on your roster '
                "can't make a position look weak."
            )
        )
    show_df(
        analysis["roster_needs"],
        "(empty roster)",
        hide_index=False,
        column_config=cols(
            analysis["roster_needs"],
            ("_index", "Pos"),
            ("count", "Count"),
            ("avg_age", "Avg Age"),
            ("young_core", "Young Core"),
            ("need", "Need"),
            ("vor", "VOR"),
            ("weak", "Weak"),
        ),
    )
    needs = analysis["need_positions"]
    if needs:
        st.info(f"Flagged needs: {', '.join(sorted(needs))} — the big board marks rookies at these positions.")
    else:
        st.info("No positions are flagged as a need right now — best available value is the main signal.")


def _render_value_analysis(analysis: dict) -> None:
    st.subheader("Roster value analysis")
    with st.expander("How this works"):
        st.caption(
            (
                'Lowest Adj. Value first.\n- **Note** — low value + aging (cutoff varies by '
                'position) is a drop candidate. Low value + young is a hold, but only while '
                'rebuilding.\n- **Status** — 🆕 rookie, ✂️ no NFL team, 🩹 injury, 🚕 taxi, 🩼 '
                'IR. Hover an icon for detail.'
            )
        )
    show_status_table(
        analysis["roster_value"],
        "(empty roster)",
        column_labels={
            "name": "Player",
            "pos": "Position",
            "age": "Age",
            "years_exp": "Years Exp",
            "status": "Status",
            "bye": "Bye",
            "value": "Value",
            "adj_value": "Adj. Value",
            "note": "Note",
        },
    )


def _render_sellable(analysis: dict) -> None:
    st.subheader("Sellable veterans")
    with st.expander("How this works"):
        st.caption(
            (
                'Bench depth at positions with surplus (VOR > 0) that could be shopped. '
                'Excludes starters, rookies, and anyone whose loss would open a weekly gap. '
                'Candidates to weigh against an offer, not recommendations.'
            )
        )
    sellable_display = analysis["sellable_players"].drop(columns="player_id", errors="ignore")
    show_df(
        sellable_display,
        "(no sellable surplus at any position right now)",
        column_config=cols(
            sellable_display,
            ("name", "Player"),
            ("pos", "Position"),
            ("age", "Age"),
            ("value", "Value"),
            ("adj_value", "Adj. Value"),
            ("position_vor", "Position VOR"),
        ),
    )


def _render_free_agents(state: dict, analysis: dict, selected_roster_id: int) -> None:
    st.subheader("Free agents")
    with st.expander("How this works"):
        st.caption(
            (
                "Unrostered players ranked by how much they'd raise this team's lineup, "
                'each with the drop it would take.\n- Adds assume an open active slot or a '
                "drop, never a taxi slot (Sleeper's taxi rule for veterans isn't "
                'modeled).\n- Pick a candidate below for FAAB bid guidance.'
            )
        )
    selected_roster_settings = state["rosters_by_id"][selected_roster_id].get("settings") or {}
    faab_remaining = state["league"]["settings"].get("waiver_budget", 0) - selected_roster_settings.get(
        "waiver_budget_used", 0
    )
    st.caption(f"Remaining FAAB: {faab_remaining}")
    board = analysis["free_agent_board"]
    show_df(
        board.drop(columns="player_id", errors="ignore"),
        "(no free agents available)",
        column_config=cols(
            board,
            ("name", "Player"),
            ("pos", "Position"),
            ("team", "NFL Team"),
            ("marginal_value", "Marginal Value"),
            ("drop_name", "Suggested Drop"),
            ("drop_is_starter", "Drop Is Starter"),
        ),
    )
    _render_faab_bid_guidance(state, board)


def _render_faab_bid_guidance(state: dict, board: pd.DataFrame) -> None:
    """Comparable FAAB bids for one selected free agent, computed on demand."""
    if board.empty or "player_id" not in board.columns:
        return

    st.markdown("**FAAB bid guidance**")
    with st.expander("How this works"):
        st.caption(
            (
                "Real winning bids from this league this season, nearest the candidate's "
                'current value, each shown with its value so you can judge the match.\n- '
                'Same position first; other positions only when the sample is thin. QB '
                'never mixes with other positions — superflex scarcity prices QBs '
                'differently.\n- Bids too far off in value are excluded.\n- Low/median/high '
                'come from the listed bids.\n- "Not enough comparable bid history yet" '
                "means too few close bids, not zero.\n\nOlder bids are compared at today's "
                'values, which is why this covers the current season only.'
            )
        )

    label_by_id = {row["player_id"]: f"{row['name']} ({row['pos']}, {row['team']})" for _, row in board.iterrows()}
    chosen_id = st.selectbox(
        "Check a candidate",
        list(label_by_id),
        format_func=lambda pid: label_by_id[pid],
        key="faab_guidance_candidate",
    )
    candidate_row = board[board["player_id"] == chosen_id].iloc[0]
    fc_entry = state["fc_by_sleeper_id"].get(chosen_id)
    adj_value = fc_entry.get("adj_value") if fc_entry else None
    position = state["players"].get(chosen_id, {}).get("position")

    if adj_value is None or pd.isna(adj_value) or position is None:
        st.info("No resolvable market value for this player yet — can't find comparable bids.")
        return

    sample = dynasty_core.won_bid_sample(state["transactions"], state["players"], state["fc_by_sleeper_id"])
    guidance = dynasty_core.bid_guidance(adj_value, position, sample)
    if guidance is None:
        st.info("Not enough comparable bid history yet this season.")
        return

    if not guidance["same_position"]:
        st.caption(f"No same-position ({position}) comparable bids yet — showing the closest bids across all positions.")
    comparables_str = ", ".join(
        f"${c['bid']:.0f} (value {c['adj_value']:.0f})" for c in guidance["comparables"]
    )
    st.write(f"Recent winning FAAB bids for similarly-valued players: {comparables_str}")
    st.caption(f"This candidate's own current value: {adj_value:.0f} — compare against each bid's value above.")
    low_col, median_col, high_col = st.columns(3)
    low_col.metric("Low", f"${guidance['low']:.0f}")
    median_col.metric("Median", f"${guidance['median']:.0f}")
    high_col.metric("High", f"${guidance['high']:.0f}")

    planned_bid = st.number_input("Your planned bid (optional)", min_value=0, step=1, value=0, key="faab_planned_bid")
    if planned_bid > 0 and planned_bid > guidance["high"]:
        message = (
            f"${planned_bid:.0f} is above the recent comparable range (up to ${guidance['high']:.0f})."
        )
        if candidate_row["marginal_value"] <= 0:
            st.warning(f"{message} This candidate also wouldn't crack your starting lineup right now.")
        else:
            st.info(message)


def _render_bye_impact(state: dict, analysis: dict) -> None:
    st.subheader("Bye week impact")
    with st.expander("How this works"):
        st.caption(
            (
                'One section per week with an active player on bye.\n- **Collapsed** — '
                'starters out, who fills in, and the lineup-value change. Bench players on '
                'bye show when expanded.\n- **✅** past week / **📅** upcoming — both are '
                "projections from today's roster.\n- A large change is worth covering via "
                'trade.'
            )
        )
    bye_impact = analysis["roster_bye_conflicts"]
    if bye_impact.empty:
        st.write("(none)")
        return

    # Sleeper's current-week counter.
    current_week = state["league"]["settings"].get("leg", 1)
    for _, row in bye_impact.iterrows():
        is_actual = row["week"] < current_week
        cue = "✅" if is_actual else "📅"
        label = f"{cue} Week {row['week']}: {row['starters_out']} → {row['fillers']} · {row['lineup_delta']:+.1f}"
        with st.expander(label):
            if is_actual:
                st.write(
                    (
                        "**Already happened** — still a projection from today's roster, not the "
                        'real result.'
                    )
                )
            else:
                st.write(
                    "**Still ahead** — projected from today's roster; will shift if the "
                    "roster changes before this week."
                )
            st.write(f"**Starters out:** {row['starters_out']}")
            st.write(f"**Fillers:** {row['fillers']}")
            st.write(f"**Lineup delta:** {row['lineup_delta']:+.1f} vs. a full-strength week (everyone available).")
            st.write(f"**Also on bye (bench, no lineup impact):** {row['bench_out']}")


def _render_weekly_gaps(analysis: dict) -> None:
    st.subheader("Weekly gaps")
    with st.expander("How this works"):
        st.caption(
            (
                "Available players per position each week vs. this league's dedicated slots "
                "(QB 1, RB 2, WR 2, TE 1). Ignores FLEX/SUPER_FLEX, so it's a rough depth "
                'check.'
            )
        )
    weekly_gaps = analysis["roster_weekly_gaps"]
    gap_weeks = weekly_gaps[weekly_gaps["gap"] != ""]
    weekly_gap_cols = cols(
        weekly_gaps, ("week", "Week"), ("QB", "QB"), ("RB", "RB"), ("WR", "WR"), ("TE", "TE"), ("gap", "Gap")
    )
    if not gap_weeks.empty:
        st.warning("Weeks with a gap:")
    show_df(gap_weeks, "No weeks have a dedicated-slot gap.", column_config=weekly_gap_cols)
    with st.expander("Show all 18 weeks"):
        st.dataframe(weekly_gaps, hide_index=True, width="stretch", column_config=weekly_gap_cols)


def _render_handcuffs(analysis: dict) -> None:
    st.subheader("Handcuff status")
    st.caption("This team's rostered RBs who are NFL starters, and whether they also own their backup.")
    show_df(
        analysis["roster_handcuffs"],
        "(none of this team's RBs are current NFL starters)",
        column_config=cols(
            analysis["roster_handcuffs"],
            ("starter", "Starter"),
            ("handcuff", "Handcuff"),
            ("handcuff_rostered", "Handcuff Rostered"),
        ),
    )


def render_roster_tab(state: dict) -> None:
    team_names_by_id = state["team_names"]
    user_roster_id = state["user_roster_id"]
    selected_roster_id = team_selectbox(
        "Viewing team", team_names_by_id, user_roster_id, "roster_tab_team_select"
    )
    # Other teams are analyzed on selection, using their own phase for the Need flag.
    if selected_roster_id == user_roster_id:
        analysis = state
    else:
        analysis = dynasty_core.team_roster_analysis(
            state["rosters_by_id"][selected_roster_id],
            state["players"],
            state["fc_by_sleeper_id"],
            state["byes"],
            state["league"],
            state["handcuffs"],
            state["replacement_level"],
            state["available_free_agents"],
            state["projections"],
            phase=str(state["team_power_timeline"].loc[selected_roster_id, "phase"]),
        )

    overview_tab, value_tab, free_agents_tab, schedule_tab = st.tabs(
        ["Overview", "Value & Handcuffs", "Free Agents", "Schedule"]
    )
    with overview_tab:
        _render_team_timeline(state, selected_roster_id)
        _render_capacity(analysis)
        _render_needs(analysis)
    with value_tab:
        _render_value_analysis(analysis)
        _render_sellable(analysis)
        _render_handcuffs(analysis)
    with free_agents_tab:
        _render_free_agents(state, analysis, selected_roster_id)
    with schedule_tab:
        _render_bye_impact(state, analysis)
        _render_weekly_gaps(analysis)
