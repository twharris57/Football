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
            "Where this team sits on a rebuild-vs-contend spectrum, recomputed fresh "
            "every refresh from current roster/standings state (not a fixed label - it "
            "reacts to injuries, trades, and results automatically).\n"
            "- **Score** — a continuous, league-wide z-scored average of three signals: "
            "roster strength (aggregate VOR across positions - see the Glossary above), "
            "timeline direction (value-weighted average age - older *established value* "
            "skews win-now), and actual win percentage. 0 = league average; positive = "
            "more win-now, negative = more rebuild-oriented. The **rank** below it (e.g. "
            "\"3 of 12\") is the same score, just easier to read at a glance than the raw "
            "number.\n"
            "- **Phase** — a display label bucketed from the score (rebuilding / "
            "treading water / contending); the score itself is the real signal.\n"
            "- **Win % before games are played** — defaults to a neutral 50%, so it "
            "contributes nothing to the score pre-season instead of distorting it with "
            "a meaningless small sample. Shown as \"no games played yet\" instead of a "
            "misleading 50% once the season actually starts, this will show a real record."
        )
    power = state["team_power_timeline"].loc[selected_roster_id]
    league_size = len(state["team_power_timeline"])
    phase_labels = {"rebuilding": "🌱 Rebuilding", "treading_water": "⚖️ Treading water", "contending": "🏆 Contending"}
    phase = str(power["phase"])
    st.metric(
        phase_labels.get(phase, phase),
        f"{int(power['rank'])} of {league_size}",
        help=(
            "Rank by power score (1 = strongest roster + timeline + record in the "
            f"league). Raw score: {power['power_score']:+.2f} (0 = league average; "
            "positive = more contending, negative = more rebuilding)."
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
            "Two different questions about each position, side by side:\n"
            "- **Need** — rebuild-timeline framing: fewer than 2 players at this position have "
            "2 years of NFL experience or less. Answers \"are we still accumulating enough young "
            "talent here.\"\n"
            "- **Weak** — trade-strategy framing: this position's actual starters (top players by "
            "value, up to this league's dedicated slot count) are worth less than **VOR** "
            "(value-over-replacement) — the value of the last startable-tier player still "
            "rostered *anywhere* in the league at that position. A position can have plenty of "
            "bodies (no Need flag) and still be Weak if none of them clear what's freely "
            "available elsewhere — or vice versa, thin in bodies but strong if the few players "
            "there are excellent.\n"
            "- VOR compares against the whole league, not the rest of *your* roster — one elite "
            "player elsewhere can't make another position look artificially weak by comparison."
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
            "Sorted lowest Adj. Value first (same real-scoring-corrected value as the big "
            "board).\n"
            "- **Note** — weighs age against a position-aware aging cutoff (RBs decline earlier "
            "than QBs/TEs): low value + young is still a rebuild asset worth holding; low value "
            "+ aging is a real drop candidate.\n"
            "- **Status** — 🆕 rookie, 🏥 injury, 🌱 taxi squad, 🩹 IR/reserve; a player can show "
            "more than one at once. Hover an icon for the specific detail (e.g. the real injury "
            "status)."
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
            "This team's own bench depth at positions with real surplus (VOR above zero - see "
            "the Glossary above), not the starters generating that VOR - selling an actual "
            "starter is a bigger call than \"there's more depth here than the roster can use,\" "
            "left for a human to judge, not this list. Only shown if dropping the player "
            "wouldn't open a weekly-depth hole. A candidate list to evaluate a specific trade "
            "against, not a recommendation - rookies are excluded (long-term upside to hold, "
            "not surplus to sell)."
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
            "Every non-rostered player, ranked by season-average marginal starting-lineup "
            "value against this team - the same ranking method the Draft Plan uses, not a "
            "different valuation model. Each row's own best drop is shown alongside it, the "
            "same cheap heuristic the ranking itself uses (not a per-candidate optimal "
            "search).\n"
            "- **Taxi squad not modeled** — Sleeper's real accrued-experience taxi rule isn't "
            "verified here, so an add is only ever suggested for an open active roster slot "
            "or via a drop, never assumed to fit an open taxi slot the way a rookie safely "
            "can.\n"
            "- **FAAB bid guidance** — pick a candidate below to see real comparable bid "
            "history and check a planned bid against it."
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
    """Real comparable FAAB bids for one selected free-agent candidate,
    computed on demand rather than for every board row every refresh - most
    rows are never looked at this closely."""
    if board.empty or "player_id" not in board.columns:
        return

    st.markdown("**FAAB bid guidance**")
    with st.expander("How this works"):
        st.caption(
            "Real winning FAAB bids from this league's own Sleeper transaction history, "
            "not an invented formula - the nearest, by current market value, to the "
            "selected candidate (same position preferred, broadened to every position "
            "only when there aren't enough same-position comparables yet), and each "
            "one's own value is shown alongside its bid so you can judge how close a "
            "match it really is. A bid whose player is too far off in value to be a "
            "meaningful comparable is excluded rather than shown anyway. QB is the one "
            "exception to broadening: this is a superflex league, so a QB can draw a real "
            "bidding premium purely from 2-QB-startable scarcity that a same-value "
            "RB/WR/TE never faces, and mixing a thin QB sample into other positions' bids "
            "would present a range built from a different demand curve than the one a QB "
            "candidate is actually being bid into - so QB guidance simply says \"not "
            "enough comparable bid history yet\" until enough real QB bids exist, rather "
            "than ever broadening, and a QB bid is likewise never shown as a broadened "
            "comparable for a non-QB candidate. Shown as the "
            "real numbers directly, plus a low/median/high computed from that exact list "
            "- never a separately-modeled number. \"Not enough comparable bid history "
            "yet\" means too few real winning bids exist close enough in value this "
            "season to say anything useful, not a hidden zero. Current season only, and "
            "each historical bid is compared against the player's *current* market "
            "value, not their value at the time of that bid - a reasonable proxy for "
            "the short in-season windows this covers, less so further back (why this "
            "doesn't yet reach into prior seasons' history)."
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
            "One collapsible section per week with an active-roster player on bye.\n"
            "- **Collapsed view** — only starters actually bumped out and who fills in, plus the "
            "lineup-value delta vs. a full-strength week. A bye'd bench player who wasn't starting "
            "anyway doesn't clutter this view (it's still shown, expanded, since it doesn't move "
            "the delta).\n"
            "- **✅** — a week that's already happened. This project has no live in-week stats "
            "yet, so the delta shown is still this same projection, not a real result.\n"
            "- **📅** — a week still ahead, projected from today's roster (it'll shift if the "
            "roster changes before then).\n"
            "- **Delta size** — a small delta means the bench covers it fine; a large one is "
            "worth looking for bye-week coverage via trade."
        )
    bye_impact = analysis["roster_bye_conflicts"]
    if bye_impact.empty:
        st.write("(none)")
        return

    # league["settings"]["leg"] is Sleeper's current-week counter for the season - not
    # otherwise used anywhere yet, but exactly what "already happened vs. still ahead" needs.
    current_week = state["league"]["settings"].get("leg", 1)
    for _, row in bye_impact.iterrows():
        is_actual = row["week"] < current_week
        cue = "✅" if is_actual else "📅"
        label = f"{cue} Week {row['week']}: {row['starters_out']} → {row['fillers']} · {row['lineup_delta']:+.1f}"
        with st.expander(label):
            if is_actual:
                st.write(
                    "**Already happened** — no live in-week stats feed into this yet, so this "
                    "is still the same roster-based projection, not a real result."
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
            "- **What it shows** — available (non-bye) rostered players per position per week, "
            "vs. what's needed to fill this league's dedicated starting slots (QB:1 RB:2 WR:2 "
            "TE:1).\n"
            "- **What it doesn't** — FLEX/SUPER_FLEX, which could pull from other positions; a "
            "rough depth signal, not a full lineup-feasibility check."
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
    # Reuse the already-computed bundle for your own team (free); any other
    # team's analysis is computed fresh here on selection - team_roster_analysis
    # is the exact same per-roster logic gather_state already ran for you,
    # just pointed at a different team's roster dict.
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
        )

    # Split into subtabs - a Roster visit used to render all nine sections
    # below as one long scrolling page; grouped by theme so only the active
    # group's content is on screen at once. Draft pick trade values moved
    # out entirely - it was already league-wide, not team-scoped, so it now
    # lives on the League tab instead (see docs/dynasty-draft-web-app.md).
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
