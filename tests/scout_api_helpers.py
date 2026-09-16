"""Shared synthetic finding payload for scout_api tests (test_finding_schema.py
and test_scout_api.py) - kept in one place so a schema change only needs
updating here rather than in two independently-drifting copies.
"""

from __future__ import annotations


def valid_finding_payload(**overrides: object) -> dict:
    payload = {
        "player_id": "4046",
        "category": "injury",
        "summary": "Questionable with a hamstring injury.",
        "source": "https://example.com/report",
        "confidence": "medium",
        "observed_at": "2026-09-10T12:00:00+00:00",
        "created_at": "2026-09-13T08:00:00+00:00",
    }
    payload.update(overrides)
    return payload
