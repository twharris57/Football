"""Load/write shell for versioned JSON snapshots that persist across refreshes.

Files are stamped with `schema_version`; `migrations[v]` upgrades v to v+1. Unstamped
files are version 0. A missing migration, or a file newer than the code, raises.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

Migration = Callable[[dict[str, Any]], dict[str, Any]]


class LoadedSnapshot(NamedTuple):
    content: dict[str, Any]
    # True when the file was migrated or unstamped: the caller should write it back.
    needs_rewrite: bool


def load_or_seed(
    path: Path,
    default: dict[str, Any],
    schema_version: int,
    migrations: dict[int, Migration] | None = None,
) -> LoadedSnapshot:
    """Load `path` migrated to `schema_version` (stamp removed), or `default` if missing."""
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
    """Write `updated` with its stamp if it differs from `existing` or `force` is set."""
    if force or updated != existing:
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({**updated, "schema_version": schema_version}), encoding="utf-8")
