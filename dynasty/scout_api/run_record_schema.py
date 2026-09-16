"""SC-4's run-record schema: one artifact per nightly cloud-routine run,
written as JSON to the `scout-data` branch (`run_YYYYMMDD.json`) and
mirrored into SQLite by `sync.py`'s `ingest_run_records()`.

Unifies three separately-designed logs into one, per
`.claude/PROJECT_PLAN_DYNASTY.md`'s SC-4 entry:

- **Dedup**: a later run scans recent run records for a matching
  `(player_id, category)` pair on a `ReviewedItem` to avoid re-surfacing
  the same thing night after night.
- **Materiality's audit trail**: every item considered that night is
  recorded with its `verdict` ("surfaced" or "suppressed") and `reason`,
  whether or not it made the cut - not just the ones that got notified.
- **Reflection state**: `reflection` starts `null` on every run and is
  the one field this schema reserves for a write path this module does
  not implement. SC-7's self-reflection pass (not yet built - hard-blocked
  on RT-21's transaction log existing) is expected to revisit a *past*
  run's file days later, once real outcomes are known, and patch this
  field in - fetch, mutate, recommit, not append-only. Nothing in this
  module performs that mutation; it only shapes the slot SC-7 will write
  into.

Two verdict lanes on `ReviewedItem`, per SC-4's plan entry: **deterministic**
(numeric thresholds already used elsewhere in this codebase - marginal
value, FAAB comparables - real, testable code) and **agentic** (Scout's
own qualitative judgment, run only after the deterministic dedup check
already passed). Only a borderline agentic verdict is expected to have
gone through SC-8's corroboration search before being recorded here.

Same prompt-injection posture as `finding_schema.py`, and the same
caveat: fixed fields and a length cap on free-text (`reason`,
`reflection.notes`) keep this store holding extracted, typed judgments
rather than a raw blob a later consumer (SC-7's own GitHub-issue text,
a future dashboard) could reason over as instructions - structural, not a
content filter. `reason`/`notes` are Scout's own generated explanation of
research content it read during SC-3's pass, so the same discipline
applies to them as to a finding's `summary`.

Deliberately stdlib-only (no `dynasty_core` import) - see
`finding_schema.py`'s module docstring for why.
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

# Scout's own generated explanation text - same UI/audit-log hygiene
# rationale as finding_schema.SUMMARY_MAX_LENGTH, not a prompt-injection
# defense by itself (see module docstring).
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
    reviewed_at: str  # ISO8601, tz-aware - when SC-7 examined this run
    notes: str
    issue_url: str | None  # a GitHub issue SC-7 opened for a missed catch


@dataclass(frozen=True)
class RunRecord:
    run_date: str  # calendar date this run covers, "YYYY-MM-DD"
    generated_at: str  # ISO8601, tz-aware - when the run actually executed
    items: tuple[ReviewedItem, ...]
    notification_fired: bool
    reflection: ReflectionState | None


def is_run_record_path(path: str) -> bool:
    """True if the GitHub path names a run-record file (e.g.
    "scout-data/run_20260916.json") rather than some other file that may
    land on scout-data (a finding, a future trade-block file, ...)."""
    return PurePosixPath(path).name.startswith(RUN_RECORD_FILENAME_PREFIX)


def _require_iso_date(payload: dict, key: str) -> str:
    value = require_nonempty_str(payload, key)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{key} is not a valid YYYY-MM-DD date: {value!r}") from exc
    # strptime accepts non-zero-padded input ("2026-9-6") but this column
    # is compared lexicographically (dedup/recency scans, see the
    # scout_run_record_items indexes) - a non-canonical value would sort
    # wrong against a normal zero-padded date, so reject it outright
    # rather than silently normalizing (no coercion, same posture as the
    # rest of this schema).
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
    """Parse and strictly validate a run_*.json file's content.

    Raises ValueError on any violation, same all-or-nothing posture as
    finding_schema.parse_finding: no defaults, no coercion, and unexpected
    keys are rejected alongside missing ones.
    """
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
