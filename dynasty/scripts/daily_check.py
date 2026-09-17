"""Cloud-routine entry point for the automated daily scout's state-
gathering step (.claude/PROJECT_PLAN_DYNASTY.md's "Automated daily scout"
section): runs `gather_state()` inside the nightly cloud routine's own
sandbox and prints a structured JSON result to stdout for that routine's
own next steps (a future nightly orchestrator) to read.

    python scripts/daily_check.py

No Streamlit dependency - `gather_state()` itself has none; this calls it
directly the way `streamlit_app.py`'s cached `load_state()` does, minus
the caching/session-state wrapper a Streamlit rerun needs.

Only the already-JSON-serializable signal fields of `gather_state()`'s
result are printed: `attention_digest` (`dict[str, list[str]]` - "what
needs attention right now", see `dynasty_core/summary.py`) and
`data_warnings` (a degraded-refresh flag, per
`valuation_principles.md`'s "silent data-degradation must surface as a
warning" rule). The rest of the returned state (every DataFrame, the full
player/roster universe, the big board) is exactly what the NAS-side
Streamlit app already renders - this script is the nightly signal a cloud
routine needs to decide whether tonight is worth a push notification, not
a second UI for the whole state.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import dynasty_core as dc  # noqa: E402


def run(league_id: str, username: str) -> dict:
    """Call `gather_state()` and return just its JSON-serializable signal fields."""
    state = dc.gather_state(league_id, username, force_full_refresh=False, force_scoring_refresh=False)
    return {
        "league_id": league_id,
        "season": state["league"]["season"],
        "current_week": state["league"]["settings"].get("leg", 1),
        "attention_digest": state["attention_digest"],
        "data_warnings": state["data_warnings"],
    }


def main() -> int:
    """Entry point. Ends in an unambiguous OK/FAIL state with a matching
    exit code, per code_conventions.md's Scripts and Automation rule -
    this runs unattended on a schedule, so there is no one present to
    interpret an ambiguous result. `gather_state()` can fail in more ways
    than the one it documents explicitly (a Sleeper/FantasyCalc outage) -
    a malformed/unexpected league response could raise a KeyError or
    similar - so this catches broadly (not a bare `except:`, which would
    also swallow SystemExit/KeyboardInterrupt) rather than risk an
    unhandled traceback standing in for a clear FAIL.
    """
    league_id = os.environ.get("DYNASTY_LEAGUE_ID", dc.DEFAULT_LEAGUE_ID)
    username = os.environ.get("DYNASTY_USERNAME", dc.DEFAULT_USERNAME)
    try:
        result = run(league_id, username)
    except Exception as exc:
        print(f"FAIL: could not gather dynasty state for league {league_id}: {exc}")
        return 1
    print(json.dumps(result, indent=2))
    print(f"OK: gathered dynasty state for league {league_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
