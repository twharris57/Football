"""Mirror the `scout-data` branch's JSON files from GitHub into local SQLite.

Runs to completion on a schedule. Set `SCOUT_DATA_GITHUB_TOKEN` to lift GitHub's
60 req/hour anonymous limit.
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

from . import db_schema, finding_schema, run_record_schema
from .scout_data_dir import DB_PATH

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
REPO = "twharris57/Football"
BRANCH = "scout-data"
BRANCH_DIR = "scout-data"

# The contents API silently truncates directory listings at this size, so exceeding it fails the sync.
GITHUB_CONTENTS_PAGE_LIMIT = 1000


def _build_session() -> requests.Session:
    """A session that retries GETs on connection errors, 429, and 5xx."""
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
    """Every JSON file directly under `scout-data/` at commit `ref`."""
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
    """Replace `table`'s rows with `rows` (keyed on `columns[0]`) inside the caller's transaction."""
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


def _fetch_and_parse(conn: sqlite3.Connection, path_predicate, parser) -> list[tuple[str, Any]]:
    """Parse every mirrored file whose path matches `path_predicate`."""
    rows = conn.execute("SELECT path, content FROM scout_data_files").fetchall()
    matching = [(row["path"], row["content"]) for row in rows if path_predicate(row["path"])]
    return [(path, parser(content)) for path, content in matching]


def ingest_findings(conn: sqlite3.Connection) -> int:
    """Upsert mirrored `finding_*.json` files into `scout_findings`; returns the count.

    All-or-nothing: a malformed finding raises ValueError and writes nothing.
    """
    parsed = _fetch_and_parse(conn, finding_schema.is_finding_path, finding_schema.parse_finding)

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


def ingest_run_records(conn: sqlite3.Connection) -> int:
    """Upsert mirrored `run_*.json` files into the run-record tables; returns the count.

    All-or-nothing: a malformed record raises ValueError and writes nothing.
    """
    parsed = _fetch_and_parse(conn, run_record_schema.is_run_record_path, run_record_schema.parse_run_record)

    with conn:
        _mirror_table(
            conn,
            "scout_run_records",
            (
                "path",
                "run_date",
                "generated_at",
                "notification_fired",
                "reflection_reviewed_at",
                "reflection_notes",
                "reflection_issue_url",
            ),
            [
                (
                    path,
                    record.run_date,
                    record.generated_at,
                    record.notification_fired,
                    record.reflection.reviewed_at if record.reflection else None,
                    record.reflection.notes if record.reflection else None,
                    record.reflection.issue_url if record.reflection else None,
                )
                for path, record in parsed
            ],
        )
        _mirror_table(
            conn,
            "scout_run_record_items",
            ("id", "path", "run_date", "player_id", "category", "verdict_lane", "verdict", "reason", "source_path"),
            [
                (
                    f"{path}:{index}",
                    path,
                    record.run_date,
                    item.player_id,
                    item.category,
                    item.verdict_lane,
                    item.verdict,
                    item.reason,
                    item.source_path,
                )
                for path, record in parsed
                for index, item in enumerate(record.items)
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
    """Sync, ingest, and exit 0 (OK) or 1 (FAIL)."""
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

        try:
            run_record_count = ingest_run_records(conn)
        except (sqlite3.Error, ValueError) as exc:
            print(f"FAIL: could not ingest run records into the local mirror: {exc}")
            return 1
    finally:
        if conn is not None:
            conn.close()
    print(
        f"OK: synced {count} file(s), ingested {finding_count} finding(s) and "
        f"{run_record_count} run record(s) into {DB_PATH}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
