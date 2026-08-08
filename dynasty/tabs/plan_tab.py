"""Draft Plan tab: round-by-round pick recommendations."""

from __future__ import annotations

import dynasty_core
import pandas as pd
import streamlit as st

from .components import cols


def render_plan_tab(state: dict) -> None:
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
            "- **Drop status** for a completed round — **✅ DROPPED** is a real drop, recovered by "
            "checking your roster across refreshes; a plain **DROP** with no checkmark is still a "
            "live guess (nothing's been checked yet); **❓ drop unclear** means more than one of your "
            "picks completed between refreshes, so which real drop paired with which pick can't be "
            "isolated; no drop text at all means it's confirmed none was needed. For rounds where the "
            "roster wasn't checked between your picks, this still has to guess.\n"
            "- **Bye weeks** are folded into the season average, not handled separately.\n"
            "- **Nothing here refreshes on its own** — no polling, no auto-refresh, in this app "
            "or the CLI. Hit the sidebar's Refresh button right before your own pick, not just "
            "after one lands elsewhere — otherwise this plan simulates as if no other team has "
            "picked in between, which can be wrong the moment your turn actually comes up.\n"
            "- Each pick is collapsed by default — expand one for the full reasoning and any "
            "backup options.\n"
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
            drop_status = row["drop_status"]
            if drop_status == "confirmed_none":
                drop_part = ""
            elif drop_status == "confirmed":
                drop_part = f" · ✅ DROPPED {row['drop_name']} ({row['drop_pos']})"
            elif drop_status == "ambiguous":
                drop_part = (
                    f" · ❓ drop unclear — guessing {row['drop_name']} ({row['drop_pos']})"
                    if pd.notna(row["drop_name"])
                    else " · ❓ drop unclear"
                )
            else:
                drop_part = f" · DROP {row['drop_name']} ({row['drop_pos']})" if pd.notna(row["drop_name"]) else ""
            warn_icon = " ⚠️" if row["drop_is_starter"] else ""
            label = (
                f"{status_icon} Round {row['round']}, pick {row['overall_pick']}: "
                f"DRAFT {row['pick_name']} ({row['pick_pos']}){drop_part}{warn_icon} · "
                f"{row['marginal_value']:+.0f}"
            )
            with st.expander(label):
                st.write(row["reason"])
                if drop_status == "ambiguous":
                    st.info(
                        "More than one of your picks completed between refreshes, so which real drop "
                        "paired with which pick can't be isolated — this is still a guess."
                    )
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
