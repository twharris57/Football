"""Summary tab: a short, curated "what needs a look right now" digest."""

from __future__ import annotations

import streamlit as st

_CATEGORY_ICONS = {
    "needs": "⚠️",
    "weekly_gaps": "⚠️",
    "sellable": "💰",
    "free_agents": "💡",
}
_CATEGORY_HEADERS = {
    "needs": "Roster needs",
    "weekly_gaps": "Weekly gap risk",
    "sellable": "Worth shopping",
    "free_agents": "Free-agent upgrades",
}


def render_summary_tab(state: dict) -> None:
    with st.expander("How this works"):
        st.caption(
            "A short digest pulled from data the other tabs already compute — no new "
            "signals, just a capped top few per category so you don't have to scroll "
            "every tab to see what's worth a look.\n"
            "- Draft-pick timing and any data warnings aren't repeated here — see the "
            "'On the clock' banner and any warning banners above, always visible "
            "regardless of tab.\n"
            "- In-season 'what changed since you last checked' isn't built yet — "
            "deferred pending a persistence layer (see `.claude/PROJECT_PLAN.md`'s "
            "`RT-9`). This is a fresh snapshot every refresh, same as every other tab.\n"
            "- Deliberately capped and not ranked across categories — a category is "
            "simply left out if it has nothing to show."
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
