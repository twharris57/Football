"""SC-2's templated finding schema: one scouted fact about an NFL player,
written as JSON to the `scout-data` branch by the not-yet-built cloud
routine (`SC-3`/`SC-6`) and mirrored into SQLite by `sync.py`'s
`ingest_findings()`.

Half of `SC-8`'s prompt-injection defense: this schema is what keeps the
store holding only extracted, typed fields rather than a raw blob a later
consumer (`SC-6`, a notification) could reason over as instructions. That
defense is structural (fixed fields, never free text) - the validation
here additionally guards against schema drift between a future `SC-3`
writer and this reader, not against injected content itself (a length cap
or an unknown-key check doesn't stop injected text that already fits
inside a typed field).

Deliberately stdlib-only (no `dynasty_core` import): `dynasty/scout_api`
is a separately built, minimal Docker image (`requests` is its only real
dependency, see its own `requirements.txt`) - pulling in anything from
`dynasty_core` would bloat that image for no reason this module needs.

No generated ID (`uuid`/`hashlib`): the GitHub file path is the natural
key, supplied externally by the caller (matching how `scout_data_files`
already keeps `path` as caller-supplied metadata, not embedded content).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath

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

# UI/notification hygiene (a push notification and a list view both want a
# bounded one-liner) - not itself a prompt-injection defense, see module
# docstring.
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
    created_at: str  # ISO8601 - when this finding was written (SC-16's retention anchor)


def is_finding_path(path: str) -> bool:
    """True if the GitHub path names a finding file (e.g.
    "scout-data/finding_....json") rather than some other file that may
    land on scout-data (a future dedup log, a status file, ...)."""
    return PurePosixPath(path).name.startswith(FINDING_FILENAME_PREFIX)


def _require_nonempty_str(payload: dict, key: str) -> str:
    value = payload[key]
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string, got {value!r}")
    return value


def _require_iso8601(payload: dict, key: str) -> str:
    value = _require_nonempty_str(payload, key)
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{key} is not a valid ISO8601 timestamp: {value!r}") from exc
    return value


def parse_finding(content: str) -> Finding:
    """Parse and strictly validate a finding_*.json file's content.

    Raises ValueError on any violation - a future SC-3 writer is expected
    to already validate against this same schema before ever committing to
    scout-data, so a failure here means schema drift or a bug upstream,
    not routine bad data to skip past silently (see sync.ingest_findings's
    own docstring for how this propagates).

    No defaults, no coercion, and unexpected keys are rejected alongside
    missing ones - both are equally a sign the writer and this reader have
    drifted out of sync.
    """
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError(f"finding content must be a JSON object, got {type(payload).__name__}")

    keys = set(payload.keys())
    if keys != _REQUIRED_KEYS:
        missing = _REQUIRED_KEYS - keys
        unexpected = keys - _REQUIRED_KEYS
        parts = []
        if missing:
            parts.append(f"missing {sorted(missing)}")
        if unexpected:
            parts.append(f"unexpected {sorted(unexpected)}")
        raise ValueError(f"finding has the wrong fields: {', '.join(parts)}")

    player_id = _require_nonempty_str(payload, "player_id")
    source = _require_nonempty_str(payload, "source")

    category = payload["category"]
    if category not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}, got {category!r}")

    confidence = payload["confidence"]
    if confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"confidence must be one of {CONFIDENCE_LEVELS}, got {confidence!r}")

    summary = _require_nonempty_str(payload, "summary")
    if len(summary) > SUMMARY_MAX_LENGTH:
        raise ValueError(f"summary exceeds {SUMMARY_MAX_LENGTH} characters ({len(summary)})")

    observed_at = _require_iso8601(payload, "observed_at")
    created_at = _require_iso8601(payload, "created_at")

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
    return json.dumps(asdict(finding), indent=2)
