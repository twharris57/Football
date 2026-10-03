"""Shared synthetic payloads for the scout_api tests."""

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


def valid_reviewed_item_payload(**overrides: object) -> dict:
    payload = {
        "player_id": "4046",
        "category": "injury",
        "verdict_lane": "deterministic",
        "verdict": "surfaced",
        "reason": "marginal_value 3.2 > 0 gate; first sighting this season.",
        "source_path": None,
    }
    payload.update(overrides)
    return payload


def valid_run_record_payload(**overrides: object) -> dict:
    payload = {
        "run_date": "2026-09-16",
        "generated_at": "2026-09-17T01:00:00+00:00",
        "items": [valid_reviewed_item_payload()],
        "notification_fired": True,
        "reflection": None,
    }
    payload.update(overrides)
    return payload
