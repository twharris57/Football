"""Pull the scout-data git branch's JSON state down from GitHub and mirror
it into local SQLite - the NAS-side half of SC-15
(.claude/PROJECT_PLAN_DYNASTY.md).

The nightly cloud routine has no persistent disk of its own between runs,
so it keeps its real state (findings, dedup log, last-run status) as JSON
files committed to a dedicated `scout-data` branch on this repo - the only
thing both the cloud routine and this NAS can reach without an inbound
connection (see PROJECT_PLAN_DYNASTY.md's "Why the inbound design was
abandoned" for why a direct API call never worked). This script is this
mirror's read side: run to completion on a schedule (Synology Task
Scheduler, invoking this image), not a long-running service - there is no
inbound port to expose here at all.

Uses GitHub's public REST API (unauthenticated works fine against this
public repo, just at GitHub's lower 60 req/hour unauthenticated rate
limit; set SCOUT_DATA_GITHUB_TOKEN to a read-only token for the standard
higher authenticated limit instead - not required for a script that runs
a few times a day).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import db_schema, finding_schema
from .scout_data_dir import DB_PATH

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
REPO = "twharris57/Football"
BRANCH = "scout-data"
BRANCH_DIR = "scout-data"

# GitHub's contents API for a directory silently truncates here with no
# error and no Link-header pagination (unlike the git trees API) - treated
# as a hard failure rather than a silent partial sync, see fetch_data_files.
GITHUB_CONTENTS_PAGE_LIMIT = 1000


def _build_session() -> requests.Session:
    """A session that retries transient failures (connection errors, 5xx, 429).

    Only GET is used here, so retrying is safe - matches
    dynasty/sleeper_api.py's own session-building pattern.
    """
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("SCOUT_DATA_GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_branch_head_sha(session: requests.Session) -> str:
    """Return the scout-data branch's current HEAD commit SHA."""
    response = session.get(
        f"{GITHUB_API_BASE}/repos/{REPO}/branches/{BRANCH}",
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["commit"]["sha"]


def fetch_data_files(session: requests.Session, ref: str) -> list[dict[str, Any]]:
    """Return every JSON file directly under scout-data/ at the given ref
    (a commit SHA, so this observes the same commit fetch_branch_head_sha()
    resolved rather than whatever the branch has moved to since)."""
    response = session.get(
        f"{GITHUB_API_BASE}/repos/{REPO}/contents/{BRANCH_DIR}",
        params={"ref": ref},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    entries = response.json()
    if len(entries) >= GITHUB_CONTENTS_PAGE_LIMIT:
        raise RuntimeError(
            f"scout-data/ listing returned {len(entries)} entries, at or above "
            f"GitHub's {GITHUB_CONTENTS_PAGE_LIMIT}-entry contents-API cap - the "
            "listing may be silently truncated; refusing to sync a possibly-"
            "incomplete file list"
        )
    return [entry for entry in entries if entry["type"] == "file" and entry["name"].endswith(".json")]


def fetch_file_content(session: requests.Session, download_url: str) -> str:
    response = session.get(download_url, headers=_headers(), timeout=30)
    response.raise_for_status()
    return response.text


def _mirror_table(conn: sqlite3.Connection, table: str, columns: tuple[str, ...], rows: list[tuple]) -> None:
    """Replace `table`'s contents with `rows` via delete-stale-then-upsert,
    inside the caller's own `with conn:` transaction.

    `columns[0]` is the primary key every row is keyed on; `rows` must carry
    values in the same order as `columns`. Shared by sync() (scout_data_files)
    and ingest_findings() (scout_findings) - both mirror an external source's
    current full state into one table, keyed the same way, and previously
    duplicated this exact delete/upsert shape independently.
    """
    key_column = columns[0]
    current_keys = [row[0] for row in rows]
    if current_keys:
        placeholders = ",".join("?" for _ in current_keys)
        conn.execute(f"DELETE FROM {table} WHERE {key_column} NOT IN ({placeholders})", current_keys)
    else:
        conn.execute(f"DELETE FROM {table}")

    column_list = ", ".join(columns)
    value_placeholders = ", ".join("?" for _ in columns)
    update_clause = ", ".join(f"{column} = excluded.{column}" for column in columns[1:])
    for row in rows:
        conn.execute(
            f"""
            INSERT INTO {table} ({column_list})
            VALUES ({value_placeholders})
            ON CONFLICT({key_column}) DO UPDATE SET {update_clause}
            """,
            row,
        )


def sync(conn: sqlite3.Connection, session: requests.Session) -> int:
    """Pull every JSON file on scout-data down and mirror it into SQLite.

    Returns the number of files ingested.
    """
    commit_sha = fetch_branch_head_sha(session)
    files = fetch_data_files(session, ref=commit_sha)
    synced_at = datetime.now(timezone.utc).isoformat()

    contents: list[tuple[str, str]] = []
    for entry in files:
        content = fetch_file_content(session, entry["download_url"])
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{entry['path']} is not valid JSON: {exc}") from exc
        contents.append((entry["path"], content))

    with conn:
        _mirror_table(
            conn,
            "scout_data_files",
            ("path", "content", "commit_sha", "synced_at"),
            [(path, content, commit_sha, synced_at) for path, content in contents],
        )
    return len(contents)


def ingest_findings(conn: sqlite3.Connection) -> int:
    """Parse every finding_*.json row already mirrored into scout_data_files
    (SC-2's templated schema, see finding_schema.py) and upsert its typed
    fields into scout_findings. Returns the number ingested.

    Reads from the local scout_data_files mirror rather than fetching fresh
    from GitHub - the content is already locally validated JSON from sync(),
    so no network access is needed here.

    Raises ValueError on the first malformed finding, aborting the whole
    ingest with nothing partially written - same all-or-nothing shape
    sync() already has for raw JSON validity. This is a deliberate
    trade-off, not an implicit side effect: SC-3's own writer is expected
    to validate against this same schema before ever committing to
    scout-data, so a failure here means schema drift or a bug upstream,
    not routine bad data to skip past silently.
    """
    rows = conn.execute("SELECT path, content FROM scout_data_files").fetchall()
    finding_rows = [(row["path"], row["content"]) for row in rows if finding_schema.is_finding_path(row["path"])]

    parsed = [(path, finding_schema.parse_finding(content)) for path, content in finding_rows]

    with conn:
        _mirror_table(
            conn,
            "scout_findings",
            ("path", "player_id", "category", "summary", "source", "confidence", "observed_at", "created_at"),
            [
                (
                    path,
                    finding.player_id,
                    finding.category,
                    finding.summary,
                    finding.source,
                    finding.confidence,
                    finding.observed_at,
                    finding.created_at,
                )
                for path, finding in parsed
            ],
        )
    return len(parsed)


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    db_schema.apply_migrations(conn)
    return conn


def main() -> int:
    """Entry point. Ends in an unambiguous OK/FAIL state with a matching
    exit code, per code_conventions.md's Scripts and Automation rule -
    this runs unattended on a schedule, so there is no one present to
    interpret an ambiguous result."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    conn: sqlite3.Connection | None = None
    try:
        try:
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = connect(str(DB_PATH))
            session = _build_session()
        except (sqlite3.Error, OSError) as exc:
            print(f"FAIL: could not open the local scout-data mirror at {DB_PATH}: {exc}")
            return 1

        try:
            count = sync(conn, session)
        except (requests.RequestException, KeyError, sqlite3.Error, ValueError, RuntimeError) as exc:
            print(f"FAIL: could not sync scout-data from GitHub: {exc}")
            return 1

        try:
            finding_count = ingest_findings(conn)
        except (sqlite3.Error, ValueError) as exc:
            print(f"FAIL: could not ingest findings into the local mirror: {exc}")
            return 1
    finally:
        if conn is not None:
            conn.close()
    print(f"OK: synced {count} file(s), ingested {finding_count} finding(s) into {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
