"""Summary tab: a short, curated "what needs a look right now" digest."""

from __future__ import annotations

import streamlit as st

_CATEGORY_ICONS = {
    "needs": "⚠️",
    "weekly_gaps": "⚠️",
    "sellable": "💰",
    "free_agents": "💡",
    "pickup_alerts": "🔔",
}
_CATEGORY_HEADERS = {
    "needs": "Roster needs",
    "weekly_gaps": "Weekly gap risk",
    "sellable": "Worth shopping",
    "free_agents": "Free-agent upgrades",
    "pickup_alerts": "Pickup alerts",
}


def render_summary_tab(state: dict) -> None:
    with st.expander("How this works"):
        st.caption(
            (
                'The top few items per category from the other tabs. Empty categories are '
                'hidden; pick timing and data warnings stay in the banners above.\n- **🔔 '
                'Pickup alerts** — free agents whose NFL team, depth-chart spot, or active '
                "status improved since the last refresh and who'd help your lineup now."
            )
        )

    digest = state["attention_digest"]
    if not any(digest.values()):
        st.success("Nothing flagged right now.")
        return

    for category, lines in digest.items():
        if not lines:
            continue
        st.subheader(_CATEGORY_HEADERS[category])
        icon = _CATEGORY_ICONS[category]
        for line in lines:
            st.caption(f"{icon} {line}")
