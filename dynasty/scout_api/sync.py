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

import logging
import os
import sqlite3
import sys
from datetime import datetime, timezone
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import db_schema
from .scout_data_dir import DB_PATH

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
REPO = "twharris57/Football"
BRANCH = "scout-data"
BRANCH_DIR = "scout-data"


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


def fetch_data_files(session: requests.Session) -> list[dict[str, Any]]:
    """Return every JSON file directly under scout-data/ on the scout-data branch."""
    response = session.get(
        f"{GITHUB_API_BASE}/repos/{REPO}/contents/{BRANCH_DIR}",
        params={"ref": BRANCH},
        headers=_headers(),
        timeout=30,
    )
    response.raise_for_status()
    entries = response.json()
    return [entry for entry in entries if entry["type"] == "file" and entry["name"].endswith(".json")]


def fetch_file_content(session: requests.Session, download_url: str) -> str:
    response = session.get(download_url, timeout=30)
    response.raise_for_status()
    return response.text


def sync(conn: sqlite3.Connection, session: requests.Session) -> int:
    """Pull every JSON file on scout-data down and mirror it into SQLite.

    Returns the number of files ingested.
    """
    commit_sha = fetch_branch_head_sha(session)
    files = fetch_data_files(session)
    synced_at = datetime.now(timezone.utc).isoformat()
    with conn:
        for entry in files:
            content = fetch_file_content(session, entry["download_url"])
            conn.execute(
                """
                INSERT INTO scout_data_files (path, content, commit_sha, synced_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    content = excluded.content,
                    commit_sha = excluded.commit_sha,
                    synced_at = excluded.synced_at
                """,
                (entry["path"], content, commit_sha, synced_at),
            )
    return len(files)


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
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(str(DB_PATH))
    session = _build_session()
    try:
        count = sync(conn, session)
    except requests.RequestException as exc:
        print(f"FAIL: could not sync scout-data from GitHub: {exc}")
        return 1
    finally:
        conn.close()
    print(f"OK: synced {count} file(s) from scout-data into {DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
