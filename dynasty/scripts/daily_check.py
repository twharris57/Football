"""Scout routine entry point: run `gather_state()` and print its signal fields as JSON.

    python scripts/daily_check.py

Prints only `attention_digest` and `data_warnings`.
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
    """Print the result and exit 0 (OK) or 1 (FAIL). Catches broadly so any failure reports FAIL."""
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
