"""Shared load/write shell for a persisted-across-refreshes JSON snapshot,
with explicit schema versioning and forward migrations.

Factored out of draft_snapshots.py (RT-20) so a second, structurally different
snapshot type (pickup_snapshots.py, RT-9) doesn't reimplement the same
load-or-seed / write-only-if-changed shape independently - see
.claude/conventions/valuation_principles.md's pattern of two independent
copies of the same logic drifting apart over time.

Every snapshot file this project persists is stamped with a `schema_version`
int on write. A caller registers a `migrations` dict mapping *the version a
migration upgrades from* to a pure function returning the next version's
shape; `load_or_seed` walks that chain automatically on load until the
content matches the caller's current `schema_version`. A file with no
`schema_version` key at all - every snapshot file written before this
mechanism existed - is treated as version 0. This never silently misreads
old-shape data as current: a version gap with no registered migration, or a
file whose stored version is *newer* than the running code's, both raise
rather than guess.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

Migration = Callable[[dict[str, Any]], dict[str, Any]]


class LoadedSnapshot(NamedTuple):
    content: dict[str, Any]
    # True whenever the file's stored schema_version didn't already match
    # what was requested (migrated, or predates versioning entirely) - the
    # caller should force a write even if its own reconcile logic finds
    # nothing new, so a file never sits indefinitely in "content says an
    # old version, code understands it as current" limbo once it's read.
    needs_rewrite: bool


def load_or_seed(
    path: Path,
    default: dict[str, Any],
    schema_version: int,
    migrations: dict[int, Migration] | None = None,
) -> LoadedSnapshot:
    """Load `path`'s JSON content, migrated up to `schema_version` and with
    the stamp stripped, or `default` if the file doesn't exist yet.

    Raises `ValueError` if the file's stored version is newer than
    `schema_version` (never silently misinterpret a newer format as a known
    older one), or if any version in the migration chain from stored to
    current has no registered function in `migrations` (never silently read
    a partially-migrated shape as current).
    """
    if not path.exists():
        return LoadedSnapshot(default, needs_rewrite=False)

    loaded = json.loads(path.read_text(encoding="utf-8"))
    stored_version = loaded.pop("schema_version", 0)
    if stored_version > schema_version:
        raise ValueError(
            f"{path} has schema_version {stored_version}, newer than this code's "
            f"{schema_version} - refusing to read a file from a newer version."
        )

    migrations = migrations or {}
    version = stored_version
    while version < schema_version:
        migrate = migrations.get(version)
        if migrate is None:
            raise ValueError(
                f"{path}: no migration registered from schema_version {version} to "
                f"{version + 1} (currently at {schema_version})."
            )
        loaded = migrate(loaded)
        version += 1

    return LoadedSnapshot(loaded, needs_rewrite=stored_version != schema_version)


def write_if_changed(
    path: Path, existing: dict[str, Any], updated: dict[str, Any], schema_version: int, force: bool = False
) -> None:
    """Write `updated` (stamped with `schema_version`) to `path` if `force`
    or it differs from `existing` (the unstamped dict `load_or_seed`
    returned).

    Avoids a disk write (and touching mtime) on a no-op refresh, unless
    `force` - pass `load_or_seed`'s `needs_rewrite` here so a migrated file
    is persisted at its new schema the moment it's touched.
    """
    if force or updated != existing:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({**updated, "schema_version": schema_version}), encoding="utf-8")
