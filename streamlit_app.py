"""Streamlit dashboard for the rookie draft big board (see dynasty_core.py).

    streamlit run streamlit_app.py

Meant to be usable from a phone during the live draft: sidebar inputs for
league ID / username, a Refresh button (re-pulls league/rosters/draft/picks —
cheap, always live), and an "Advanced refresh" section (players/values cache
bust, plus a scoring-multiplier prewarm) — the web equivalent of the CLI's
Enter-vs-`f` prompt, split further so the slow multiplier recompute (1-2
min) is never an accidental side effect of a routine refresh, but is still
reachable from a phone if the user needs to prewarm it away from a terminal.
"""

from __future__ import annotations

import html
import os

import pandas as pd
import requests
import streamlit as st

import dynasty_core

APP_VERSION = os.environ.get("GIT_SHA", "dev")[:7]


def show_df(
    df: pd.DataFrame,
    empty_message: str,
    *,
    hide_index: bool = True,
    column_config: dict[str, object] | None = None,
) -> bool:
    """Render df, or empty_message if it's empty - the repeated shape across every tab.

    Returns whether df had rows, so callers can compose extra logic (an
    extra warning, an expander) on the non-empty path. `column_config` is
    passed straight through to st.dataframe - display-only relabeling
    (see the `cols()` helper below), the underlying column names (and
    every reference to them elsewhere in this codebase) are untouched.
    """
    if df.empty:
        st.write(empty_message)
        return False
    st.dataframe(df, hide_index=hide_index, width="stretch", column_config=column_config)
    return True


def cols(df: pd.DataFrame, *specs: tuple[str, str] | tuple[str, str, str]) -> dict[str, object]:
    """Build a column_config dict from (key, label) or (key, label, help_text) tuples.

    Human-readable table headers without renaming the underlying DataFrame
    columns everything else in this codebase (and its tests) refers to by
    their plain snake_case names. `df` is only consulted for dtypes, never
    modified - any float column (adj_value, value, avg_age, ...) gets a
    NumberColumn capped to 2 decimal digits instead of st.dataframe's
    default of showing whatever precision the underlying computation
    happened to produce (e.g. adj_value's real-scoring multiplier leaves
    values like 7827.988709). Display-only, same as the label relabeling
    itself - the DataFrame's actual values, and everything else that reads
    them, are untouched.
    """
    config: dict[str, object] = {}
    for spec in specs:
        key, label = spec[0], spec[1]
        help_text = spec[2] if len(spec) == 3 else None
        if key in df.columns and pd.api.types.is_float_dtype(df[key]):
            config[key] = st.column_config.NumberColumn(label, help=help_text, format="%.2f")
        else:
            config[key] = st.column_config.Column(label, help=help_text)
    return config


def show_status_table(df: pd.DataFrame, empty_message: str, column_labels: dict[str, str]) -> None:
    """Render df (must have a `status_details` column, see dynasty_core.player_status_details)
    as a plain HTML table instead of st.dataframe, so each player's status icons get a real
    per-cell hover tooltip with the specific detail (e.g. the actual injury_status word).
    st.dataframe's column_config only supports a per-column tooltip (see cols()'s help text
    elsewhere), not per-cell, so this one table can't use the shared show_df approach.
    """
    if df.empty:
        st.write(empty_message)
        return

    display_cols = [c for c in df.columns if c != "status_details"]
    header_html = "".join(
        f"<th style='text-align:left; padding:4px 8px; "
        f"border-bottom:1px solid rgba(128,128,128,0.4);'>{html.escape(column_labels.get(c, c))}</th>"
        for c in display_cols
    )

    body_rows = []
    for _, row in df.iterrows():
        cells = []
        for c in display_cols:
            if c == "status":
                details = row.get("status_details") or []
                cell = " ".join(f'<span title="{html.escape(desc)}">{icon}</span>' for icon, desc in details)
            else:
                value = row[c]
                if pd.isna(value):
                    cell = ""
                elif isinstance(value, float):
                    # numpy.float64 (what a pandas row actually holds) is a
                    # float subclass, so this also catches adj_value/value/bye
                    # - capped to 2 decimals same as every other table
                    # (see cols()), not whatever precision the value happens
                    # to carry (e.g. adj_value's real-scoring multiplier).
                    cell = html.escape(f"{value:.2f}")
                else:
                    cell = html.escape(str(value))
            cells.append(
                f"<td style='padding:4px 8px; border-bottom:1px solid rgba(128,128,128,0.15);'>{cell}</td>"
            )
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    table_html = (
        "<div style='overflow-x:auto;'><table style='width:100%; border-collapse:collapse; "
        f"font-size:0.9rem;'><thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table></div>"
    )
    st.markdown(table_html, unsafe_allow_html=True)

st.set_page_config(page_title="Dynasty Rookie Draft", layout="centered")

if "league_name" not in st.session_state:
    st.session_state.league_name = "League"

st.sidebar.header(st.session_state.league_name)
league_id = st.sidebar.text_input("League ID", value=dynasty_core.DEFAULT_LEAGUE_ID)
username = st.sidebar.text_input("Username", value=dynasty_core.DEFAULT_USERNAME)

if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = 0
if "force_refresh_pending" not in st.session_state:
    st.session_state.force_refresh_pending = False
if "force_scoring_pending" not in st.session_state:
    st.session_state.force_scoring_pending = False

refresh = st.sidebar.button("Refresh")
with st.sidebar.expander("Advanced refresh"):
    st.caption(
        "Force-bust caches instead of waiting for their normal TTL. The scoring-multiplier "
        "prewarm takes 1-2 minutes (re-imports 3 seasons of weekly + play-by-play data) - do "
        "this ahead of draft day, not while on the clock."
    )
    refresh_players = st.checkbox("Players + market values (fast)", value=True)
    refresh_scoring = st.checkbox("Recompute scoring multipliers (slow, 1-2 min)")
    apply_advanced = st.button("Apply advanced refresh")

if refresh or apply_advanced:
    st.session_state.refresh_token += 1
    # A widget button/checkbox's value is only current on the exact run it
    # was clicked - any later rerun (e.g. opening an expander) can see a
    # stale/default value again. load_state's cache key must not depend on
    # that raw, one-run-only value (it did before - see PROJECT_PLAN.md),
    # or the very next rerun after a refresh click gets a different key,
    # misses cache, and silently re-fetches for no reason. These two flags
    # are durable session_state instead, stable across reruns until the
    # next actual button click changes refresh_token again.
    st.session_state.force_refresh_pending = apply_advanced and refresh_players
    st.session_state.force_scoring_pending = apply_advanced and refresh_scoring


@st.cache_data(show_spinner="Loading draft state...")
def load_state(
    league_id: str, username: str, force_full_refresh: bool, force_scoring_refresh: bool, _token: int
) -> dict:
    return dynasty_core.gather_state(league_id, username, force_full_refresh, force_scoring_refresh)


st.title("Dynasty Rookie Draft")

try:
    state = load_state(
        league_id,
        username,
        st.session_state.force_refresh_pending,
        st.session_state.force_scoring_pending,
        st.session_state.refresh_token,
    )
except requests.RequestException as exc:
    # gather_state() names which of the two services (Sleeper/FantasyCalc)
    # actually failed.
    st.error(f"{exc}. Hit Refresh to try again.")
    st.stop()
except ValueError as exc:
    st.error(str(exc))
    st.stop()

league = state["league"]
st.session_state.league_name = league["name"]
st.caption(f"{league['name']} - {league['season']} Rookie Draft ({league['status']})")

for warning in state["data_warnings"]:
    st.warning(warning)

total_picks = len(state["ownership"])
current_pick_no = state["current_pick_no"]
if current_pick_no > total_picks:
    st.success("Draft complete.")
else:
    on_the_clock = next(p for p in state["ownership"] if p.overall_pick == current_pick_no)
    clock_team = state["team_names"][on_the_clock.owner_roster_id]
    until_turn = state["picks_until_turn"]
    if until_turn is None:
        turn_note = " (no picks left this draft)"
    elif until_turn == 0:
        turn_note = " — **your turn!**"
    else:
        turn_note = f" ({until_turn} pick{'s' if until_turn != 1 else ''} until your turn)"
    st.info(f"On the clock: pick {current_pick_no}/{total_picks} - {clock_team}{turn_note}")

plan_tab, lineup_tab, draft_tab, roster_tab = st.tabs(["Draft Plan", "Lineup", "Draft Board", "Your Roster"])

with plan_tab:
    with st.expander("How this works"):
        st.caption(
            "Picks are ranked by season-average **marginal** starting-lineup value, not raw trade "
            "value — for each candidate, this simulates adding them (+ the resulting drop) and "
            "measures how much your roster's season-average starting value goes up. A modest "
            "player at a weak position can beat a highly-valued one who wouldn't crack your "
            "lineup.\n"
            "- **✅** — a round Sleeper has already recorded, scored the same way retroactively.\n"
            "- **🔜** — a round that's simulated, assuming no other team's picks happen in "
            "between (\"if these were your only remaining picks, back to back, on the board "
            "right now\").\n"
            "- **⚠️** — the suggested drop is a current starter.\n"
            "- **Drop suggestion** — a live suggestion even for a completed round; Sleeper has no "
            "record of whether it was actually dropped.\n"
            "- **Bye weeks** are folded into the season average, not handled separately.\n"
            "- Each pick is collapsed by default — expand one for the full reasoning and any "
            "backup options. Refresh after any pick lands for an updated plan.\n"
            "- **Player projection lookup** — every candidate considered for that pick, not just "
            "the top few, is one dropdown click away. Its marginal value uses the same quick "
            "drop heuristic as the ranking above (lowest-value bench player) — the best drop "
            "shown below it is searched specifically for that candidate instead, among players "
            "who share a slot type with them, so it can actually differ pick to pick."
        )
    plan = state["multi_round_plan"]
    rounds = plan["rounds"]
    if rounds.empty:
        st.write("(no picks owned this draft)")
    else:
        alternates_by_pick = plan["alternates_by_pick"]
        all_candidates_by_pick = plan["all_candidates_by_pick"]
        hypothetical_ids_by_pick = plan["hypothetical_ids_by_pick"]
        for _, row in rounds.iterrows():
            status_icon = "✅" if row["status"] == "completed" else "🔜"
            drop_part = f" · DROP {row['drop_name']} ({row['drop_pos']})" if pd.notna(row["drop_name"]) else ""
            warn_icon = " ⚠️" if row["drop_is_starter"] else ""
            label = (
                f"{status_icon} Round {row['round']}, pick {row['overall_pick']}: "
                f"DRAFT {row['pick_name']} ({row['pick_pos']}){drop_part}{warn_icon} · "
                f"{row['marginal_value']:+.0f}"
            )
            with st.expander(label):
                st.write(row["reason"])
                if row["drop_is_starter"]:
                    st.warning(f"{row['drop_name']} is a current starter.")
                alternates = alternates_by_pick.get(row["overall_pick"])
                if alternates is not None and not alternates.empty:
                    st.caption("Backup options for this pick:")
                    st.dataframe(
                        alternates,
                        hide_index=True,
                        width="stretch",
                        column_config=cols(
                            alternates,
                            ("name", "Player"),
                            ("pos", "Position"),
                            ("marginal_value", "Marginal Value"),
                            ("drop_name", "Drop"),
                            ("drop_is_starter", "Drop Is Starter"),
                            ("notes", "Notes"),
                        ),
                    )

                candidates = all_candidates_by_pick.get(row["overall_pick"])
                if candidates is not None and not candidates.empty:
                    st.caption(
                        "Check any other available player's projected marginal value for this pick "
                        f"(all {len(candidates)} evaluated, best first):"
                    )
                    option_labels = [
                        f"{c['name']} ({c['pos']}) — {c['marginal_value']:+.1f}"
                        for _, c in candidates.iterrows()
                    ]
                    chosen = st.selectbox(
                        "Player projection lookup",
                        option_labels,
                        key=f"projection_lookup_{row['overall_pick']}",
                        label_visibility="collapsed",
                    )
                    selected = candidates.iloc[option_labels.index(chosen)]
                    # The best drop for THIS specific candidate, not the
                    # cheap lowest-value-bench-player heuristic the ranking
                    # above uses (which repeats the same answer across very
                    # different candidates) - searched fresh here since it's
                    # only ever needed for the one candidate picked from the
                    # dropdown, not all of them.
                    best_drop = dynasty_core.best_position_relevant_drop(
                        selected["player_id"],
                        hypothetical_ids_by_pick[row["overall_pick"]],
                        state["players"],
                        state["fc_by_sleeper_id"],
                        state["byes"],
                        state["league"],
                        state["ineligible_ids"],
                    )
                    if best_drop is None:
                        drop_text = "no drop needed"
                    else:
                        drop_text = f"best drop: **{best_drop['name']}** ({best_drop['pos']})"
                        if best_drop["is_starter"]:
                            drop_text += " — a current starter"
                    st.write(
                        f"**{selected['name']}** ({selected['pos']}): {selected['marginal_value']:+.1f} "
                        f"marginal value (ranking estimate) — {drop_text}"
                    )
                    if best_drop is not None:
                        st.caption(
                            f"Marginal value with this specific drop: {best_drop['marginal_value']:+.1f} — "
                            "searched only among players sharing a slot type with this candidate (own "
                            "position, FLEX, or SUPER_FLEX as applicable), so it can differ from the "
                            "estimate above."
                        )

    st.subheader("Weekly gap impact")
    alerts = plan["weekly_gap_alerts"]
    if alerts.empty:
        st.success("This plan does not introduce any new weekly gaps.")
    else:
        st.warning("This plan would introduce or worsen a gap in these weeks:")
        st.dataframe(
            alerts,
            hide_index=True,
            width="stretch",
            column_config=cols(alerts, ("week", "Week"), ("gap_before", "Gap Before"), ("gap_after", "Gap After")),
        )

with lineup_tab:
    st.caption(
        "Optimal current lineup by value alone — a snapshot, not week-specific yet (doesn't "
        "account for byes or injuries when deciding who starts). A by-week/injury-aware version "
        "is a planned refinement."
    )
    starter_cols = cols(
        state["lineup_starters"], ("slot", "Slot"), ("name", "Player"), ("pos", "Position"), ("adj_value", "Value")
    )
    bench_cols = cols(state["lineup_bench"], ("name", "Player"), ("pos", "Position"), ("adj_value", "Value"))
    st.subheader("Starters")
    st.dataframe(state["lineup_starters"], hide_index=True, width="stretch", column_config=starter_cols)
    st.subheader("Bench")
    show_df(state["lineup_bench"], "(empty)", column_config=bench_cols)
    st.subheader("Taxi squad")
    show_df(state["lineup_taxi"], "(empty)", column_config=bench_cols)
    st.subheader("IR / Reserve")
    show_df(state["lineup_ir"], "(empty)", column_config=bench_cols)

with draft_tab:
    st.subheader("Your picks")
    show_df(
        state["your_picks"],
        "(none)",
        column_config=cols(
            state["your_picks"],
            ("round", "Round"),
            ("overall_pick", "Pick #"),
            ("status", "Status"),
            ("acquired_from", "Acquired From"),
        ),
    )

    if not state["recent_picks"].empty:
        st.subheader("Recently drafted")
        st.dataframe(
            state["recent_picks"],
            hide_index=True,
            width="stretch",
            column_config=cols(
                state["recent_picks"], ("pick", "Pick #"), ("team", "Team"), ("player", "Player"), ("pos", "Position")
            ),
        )

    st.subheader("Rookie big board")
    with st.expander("How this works"):
        st.caption(
            "The whole rookie class — drafted players stay listed instead of disappearing.\n"
            "- **Rank** — value order across the whole class, drafted and undrafted together.\n"
            "- **Drafted Round / Drafted By** — blank if still undrafted.\n"
            "- **Value** — FantasyCalc's raw number.\n"
            "- **Adj. Value** — applies this league's real-scoring correction (see the Draft Plan "
            "tab) and is what determines sort order and Rank.\n"
            "- **Tier** — FantasyCalc's own global tier across *all* players, not rookie-specific "
            "and not adjusted; gaps in the sequence are veterans/other rookies not shown here.\n"
            "- **Fits Need** — flags a currently-thin position on your roster.\n"
            "- **Handcuff To** — this rookie backs up one of your own RB starters. Expect this to "
            "be sparse pre-season: `nfl_data_py`'s player-ID crosswalk hasn't caught up with most "
            "of this year's incoming class yet — not a bug, should fill in later in the year."
        )
    board = state["big_board"]
    if board.empty:
        st.write("(no rookies available)")
    else:
        board_cols = cols(
            board,
            ("rank", "Rank"),
            ("name", "Player"),
            ("pos", "Position"),
            ("fits_need", "Fits Need"),
            ("handcuff_to", "Handcuff To"),
            ("drafted_round", "Drafted Round"),
            ("drafted_by", "Drafted By"),
            ("team", "Team"),
            ("college", "College"),
            ("age", "Age"),
            ("value", "Value"),
            ("adj_value", "Adj. Value"),
        )
        for tier in sorted(board["tier"].unique()):
            st.markdown(f"**Tier {tier}**")
            st.dataframe(
                board[board["tier"] == tier].drop(columns="tier"),
                hide_index=True,
                width="stretch",
                column_config=board_cols,
            )

with roster_tab:
    team_names_by_id = state["team_names"]
    user_roster_id = state["user_roster_id"]
    roster_id_options = sorted(team_names_by_id, key=lambda rid: (rid != user_roster_id, team_names_by_id[rid]))
    selected_roster_id = st.selectbox(
        "Viewing team",
        roster_id_options,
        format_func=lambda rid: team_names_by_id[rid] + (" (you)" if rid == user_roster_id else ""),
        key="roster_tab_team_select",
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
        )

    st.subheader("Roster capacity")
    cap = analysis["roster_capacity"]
    cap_col1, cap_col2, cap_col3 = st.columns(3)
    cap_col1.metric("Active roster", f"{cap['active_filled']}/{cap['active_total']}", f"{cap['active_open']} open")
    cap_col2.metric("Taxi squad", f"{cap['taxi_filled']}/{cap['taxi_total']}", f"{cap['taxi_open']} open")
    cap_col3.metric("IR / Reserve", f"{cap['reserve_filled']}/{cap['reserve_total']}", f"{cap['reserve_open']} open")
    if cap["active_open"] <= 0 and cap["taxi_open"] <= 0:
        st.warning("No open roster or taxi slots — drafting a rookie means dropping someone first.")

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
    else:
        # league["settings"]["leg"] is Sleeper's current-week counter for the season - not
        # otherwise used anywhere yet, but exactly what "already happened vs. still ahead" needs.
        current_week = league["settings"].get("leg", 1)
        for _, row in bye_impact.iterrows():
            is_actual = row["week"] < current_week
            cue = "✅" if is_actual else "📅"
            label = (
                f"{cue} Week {row['week']}: {row['starters_out']} → {row['fillers']} · "
                f"{row['lineup_delta']:+.1f}"
            )
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

st.divider()
st.caption(f"Dynasty Rookie Draft · build {APP_VERSION}")
