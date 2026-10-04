"""Finding schema: one scouted fact about a player, as JSON on the `scout-data` branch.

Fixed typed fields, never free text, so downstream consumers can't treat scouted
content as instructions. Stdlib-only to keep the scout image minimal. The GitHub
path is the key.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from .schema_validation import require_exact_keys, require_iso8601, require_nonempty_str

CATEGORIES = (
    "injury",
    "role_change",
    "depth_chart",
    "transaction",
    "trade_rumor",
    "performance_trend",
    "other",
)
CONFIDENCE_LEVELS = ("low", "medium", "high")

# Keeps notifications and list rows to one line; not an injection defense.
SUMMARY_MAX_LENGTH = 300

FINDING_FILENAME_PREFIX = "finding_"

_REQUIRED_KEYS = frozenset(
    {"player_id", "category", "summary", "source", "confidence", "observed_at", "created_at"}
)


@dataclass(frozen=True)
class Finding:
    player_id: str
    category: str
    summary: str
    source: str
    confidence: str
    observed_at: str  # ISO8601 - when the real-world event happened
    # ISO8601 - when this finding was written; anchors retention pruning
    created_at: str


def is_finding_path(path: str) -> bool:
    """True if the GitHub path is a `finding_*.json` file."""
    return PurePosixPath(path).name.startswith(FINDING_FILENAME_PREFIX)


def parse_finding(content: str) -> Finding:
    """Parse a finding strictly: no defaults, no coercion, exact keys. Raises ValueError."""
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError(f"finding content must be a JSON object, got {type(payload).__name__}")

    require_exact_keys(payload, _REQUIRED_KEYS, "finding")

    player_id = require_nonempty_str(payload, "player_id")
    source = require_nonempty_str(payload, "source")

    category = payload["category"]
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}, got {category!r}")

    confidence = payload["confidence"]
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}, got {confidence!r}")

    summary = require_nonempty_str(payload, "summary")
    if len(summary) > SUMMARY_MAX_LENGTH:
        raise ValueError(f"summary exceeds {SUMMARY_MAX_LENGTH} characters ({len(summary)})")

    observed_at = require_iso8601(payload, "observed_at")
    created_at = require_iso8601(payload, "created_at")

    return Finding(
        player_id=player_id,
        category=category,
        summary=summary,
        source=source,
        confidence=confidence,
        observed_at=observed_at,
        created_at=created_at,
    )


def finding_to_json(finding: Finding) -> str:
    """Serialize a Finding back to the same JSON shape parse_finding reads."""
    return json.dumps(asdict(finding), indent=2)
