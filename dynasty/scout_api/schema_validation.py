"""Strict validators for scout JSON: no defaults, no coercion, exact keys, tz-aware timestamps."""

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
        # "" would be a third state alongside null and a real value.
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
    """Raise ValueError unless the keys match exactly; `label` names the object in the error."""
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
