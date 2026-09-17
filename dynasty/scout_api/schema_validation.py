"""Shared strict-field validators for scout_api's templated JSON schemas
(finding_schema.py, run_record_schema.py) - both parse content committed
to the `scout-data` branch with the same all-or-nothing posture: no
defaults, no coercion, exact field sets, and a tz-aware requirement on
every timestamp (see finding_schema.py's own module docstring for why
that requirement exists).
"""

from __future__ import annotations

from datetime import datetime


def require_nonempty_str(payload: dict, key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string, got {value!r}")
    return value


def require_nullable_str(payload: dict, key: str) -> str | None:
    value = payload[key]
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        # Reject "" alongside non-strings: a nullable field means "null, or
        # a real value" - letting "" through as a third, distinct state
        # only invites disagreement downstream between an `is None` check
        # and a truthy check on the same stored value.
        raise ValueError(f"{key} must be a non-empty string or null, got {value!r}")
    return value


def require_iso8601(payload: dict, key: str) -> str:
    value = require_nonempty_str(payload, key)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{key} is not a valid ISO8601 timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{key} must include a UTC offset, got a timezone-naive timestamp: {value!r}")
    return value


def require_exact_keys(payload: dict, required_keys: frozenset[str], label: str) -> None:
    """Raise ValueError unless payload's keys exactly match required_keys.

    label names the thing being validated in the error message (e.g.
    "finding", "items[0]", "reflection") - both missing and unexpected
    keys are equally a sign of schema drift, per this module's own
    all-or-nothing posture.
    """
    keys = set(payload.keys())
    if keys != required_keys:
        missing = required_keys - keys
        unexpected = keys - required_keys
        parts = []
        if missing:
            parts.append(f"missing {sorted(missing)}")
        if unexpected:
            parts.append(f"unexpected {sorted(unexpected)}")
        raise ValueError(f"{label} has the wrong fields: {', '.join(parts)}")
