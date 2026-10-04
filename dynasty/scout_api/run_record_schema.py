"""Run-record schema: one `run_YYYYMMDD.json` per nightly scout run.

Serves three purposes:
- **Dedup:** later runs skip `(player_id, category)` pairs already reviewed.
- **Audit:** every item considered, with its verdict and reason.
- **Reflection:** `reflection` starts null; a later pass patches it in.

Verdicts come from a deterministic lane (numeric thresholds) or an agentic lane
(Scout's judgment, after dedup). Free text is length-capped. Stdlib-only.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath

from .finding_schema import CATEGORIES
from .schema_validation import require_exact_keys, require_iso8601, require_nonempty_str, require_nullable_str

VERDICT_LANES = ("deterministic", "agentic")
VERDICTS = ("surfaced", "suppressed")

# Length cap for display and audit logs; not an injection defense.
REASON_MAX_LENGTH = 500
REFLECTION_NOTES_MAX_LENGTH = 1000

RUN_RECORD_FILENAME_PREFIX = "run_"

_ITEM_REQUIRED_KEYS = frozenset(
    {"player_id", "category", "verdict_lane", "verdict", "reason", "source_path"}
)
_REFLECTION_REQUIRED_KEYS = frozenset({"reviewed_at", "notes", "issue_url"})
_RUN_RECORD_REQUIRED_KEYS = frozenset(
    {"run_date", "generated_at", "items", "notification_fired", "reflection"}
)


@dataclass(frozen=True)
class ReviewedItem:
    player_id: str
    category: str
    verdict_lane: str  # one of VERDICT_LANES
    verdict: str  # one of VERDICTS
    reason: str
    source_path: str | None  # the finding_*.json path this came from, if any


@dataclass(frozen=True)
class ReflectionState:
    # ISO8601, tz-aware - when reflection examined this run
    reviewed_at: str
    notes: str
    # GitHub issue opened for a missed catch, if any
    issue_url: str | None


@dataclass(frozen=True)
class RunRecord:
    run_date: str  # calendar date this run covers, "YYYY-MM-DD"
    generated_at: str  # ISO8601, tz-aware - when the run actually executed
    items: tuple[ReviewedItem, ...]
    notification_fired: bool
    reflection: ReflectionState | None


def is_run_record_path(path: str) -> bool:
    """True if the GitHub path is a `run_*.json` file."""
    return PurePosixPath(path).name.startswith(RUN_RECORD_FILENAME_PREFIX)


def _require_iso_date(payload: dict, key: str) -> str:
    value = require_nonempty_str(payload, key)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{key} is not a valid YYYY-MM-DD date: {value!r}") from exc
    # Require zero-padding: the column is compared as text.
    if parsed.strftime("%Y-%m-%d") != value:
        raise ValueError(f"{key} must be zero-padded YYYY-MM-DD, got {value!r}")
    return value


def _parse_reviewed_item(payload: object, index: int) -> ReviewedItem:
    if not isinstance(payload, dict):
        raise ValueError(f"items[{index}] must be a JSON object, got {type(payload).__name__}")

    require_exact_keys(payload, _ITEM_REQUIRED_KEYS, f"items[{index}]")

    player_id = require_nonempty_str(payload, "player_id")

    category = payload["category"]
    if category not in CATEGORIES:
        raise ValueError(f"items[{index}].category must be one of {CATEGORIES}, got {category!r}")

    verdict_lane = payload["verdict_lane"]
    if verdict_lane not in VERDICT_LANES:
        raise ValueError(
            f"items[{index}].verdict_lane must be one of {VERDICT_LANES}, got {verdict_lane!r}"
        )

    verdict = payload["verdict"]
    if verdict not in VERDICTS:
        raise ValueError(f"items[{index}].verdict must be one of {VERDICTS}, got {verdict!r}")

    reason = require_nonempty_str(payload, "reason")
    if len(reason) > REASON_MAX_LENGTH:
        raise ValueError(f"items[{index}].reason exceeds {REASON_MAX_LENGTH} characters ({len(reason)})")

    source_path = require_nullable_str(payload, "source_path")

    return ReviewedItem(
        player_id=player_id,
        category=category,
        verdict_lane=verdict_lane,
        verdict=verdict,
        reason=reason,
        source_path=source_path,
    )


def _parse_reflection(payload: object) -> ReflectionState | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise ValueError(f"reflection must be a JSON object or null, got {type(payload).__name__}")

    require_exact_keys(payload, _REFLECTION_REQUIRED_KEYS, "reflection")

    reviewed_at = require_iso8601(payload, "reviewed_at")
    notes = require_nonempty_str(payload, "notes")
    if len(notes) > REFLECTION_NOTES_MAX_LENGTH:
        raise ValueError(f"reflection.notes exceeds {REFLECTION_NOTES_MAX_LENGTH} characters ({len(notes)})")
    issue_url = require_nullable_str(payload, "issue_url")

    return ReflectionState(reviewed_at=reviewed_at, notes=notes, issue_url=issue_url)


def parse_run_record(content: str) -> RunRecord:
    """Parse a run record strictly: no defaults, no coercion, exact keys. Raises ValueError."""
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError(f"run record content must be a JSON object, got {type(payload).__name__}")

    require_exact_keys(payload, _RUN_RECORD_REQUIRED_KEYS, "run record")

    run_date = _require_iso_date(payload, "run_date")
    generated_at = require_iso8601(payload, "generated_at")

    items_payload = payload["items"]
    if not isinstance(items_payload, list):
        raise ValueError(f"items must be a JSON array, got {type(items_payload).__name__}")
    items = tuple(_parse_reviewed_item(item, index) for index, item in enumerate(items_payload))

    notification_fired = payload["notification_fired"]
    if not isinstance(notification_fired, bool):
        raise ValueError(f"notification_fired must be a boolean, got {notification_fired!r}")

    reflection = _parse_reflection(payload["reflection"])

    return RunRecord(
        run_date=run_date,
        generated_at=generated_at,
        items=items,
        notification_fired=notification_fired,
        reflection=reflection,
    )


def run_record_to_json(run_record: RunRecord) -> str:
    """Serialize a RunRecord back to the same JSON shape parse_run_record reads."""
    return json.dumps(asdict(run_record), indent=2)
