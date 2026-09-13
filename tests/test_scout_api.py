"""Tests for dynasty/scout_api's outbound sync: pulling the scout-data
branch's JSON state down from GitHub and mirroring it into SQLite (SC-15,
.claude/PROJECT_PLAN_DYNASTY.md).

No real network calls - a fake `requests.Session` stands in for GitHub's
API, matching testing.md's "mock only external services you do not
control" exception for a genuine third-party API boundary (the same
pattern tests/test_sleeper_api.py already uses). The SQLite side is a
real in-memory connection with real migrations applied - no mocking of a
boundary this project owns.
"""

from __future__ import annotations

import json
import sqlite3

from scout_api import db_schema, sync


class FakeResponse:
    def __init__(self, payload=None, text=None):
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


class FakeSession:
    """Dispatches GitHub API calls by URL, matching sync.py's own request shapes."""

    def __init__(self, branch_sha: str, contents: list[dict], file_bodies: dict[str, str]):
        self.branch_sha = branch_sha
        self.contents = contents
        self.file_bodies = file_bodies
        self.calls: list[str] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if url == f"{sync.GITHUB_API_BASE}/repos/{sync.REPO}/branches/{sync.BRANCH}":
            return FakeResponse({"commit": {"sha": self.branch_sha}})
        if url == f"{sync.GITHUB_API_BASE}/repos/{sync.REPO}/contents/{sync.BRANCH_DIR}":
            return FakeResponse(self.contents)
        if url in self.file_bodies:
            return FakeResponse(text=self.file_bodies[url])
        raise AssertionError(f"unexpected URL requested: {url}")


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    db_schema.apply_migrations(conn)
    return conn


class TestBuildSession:
    def test_retries_only_transient_failure_statuses_on_get(self):
        session = sync._build_session()
        retry = session.get_adapter("https://api.github.com").max_retries

        assert retry.total == 3
        assert retry.backoff_factor == 0.5
        assert retry.status_forcelist == (429, 500, 502, 503, 504)
        assert retry.allowed_methods == ("GET",)


class TestHeaders:
    def test_omits_authorization_when_no_token_set(self, monkeypatch):
        monkeypatch.delenv("SCOUT_DATA_GITHUB_TOKEN", raising=False)

        headers = sync._headers()

        assert "Authorization" not in headers

    def test_includes_bearer_token_when_set(self, monkeypatch):
        monkeypatch.setenv("SCOUT_DATA_GITHUB_TOKEN", "test-token")

        headers = sync._headers()

        assert headers["Authorization"] == "Bearer test-token"


class TestSync:
    def test_ingests_only_json_files_and_records_commit_sha(self):
        conn = _fresh_conn()
        contents = [
            {"type": "file", "name": "status.json", "path": "scout-data/status.json", "download_url": "https://raw/status"},
            {"type": "file", "name": "notes.txt", "path": "scout-data/notes.txt", "download_url": "https://raw/notes"},
            {"type": "dir", "name": "sub", "path": "scout-data/sub", "download_url": None},
        ]
        session = FakeSession(branch_sha="abc123", contents=contents, file_bodies={"https://raw/status": '{"ok": true}'})

        count = sync.sync(conn, session)

        assert count == 1
        row = conn.execute("SELECT * FROM scout_data_files WHERE path = ?", ("scout-data/status.json",)).fetchone()
        assert row["content"] == '{"ok": true}'
        assert row["commit_sha"] == "abc123"

    def test_resyncing_updates_the_existing_row_rather_than_duplicating(self):
        conn = _fresh_conn()
        contents = [
            {"type": "file", "name": "status.json", "path": "scout-data/status.json", "download_url": "https://raw/status"},
        ]
        first = FakeSession(branch_sha="sha1", contents=contents, file_bodies={"https://raw/status": '{"n": 1}'})
        sync.sync(conn, first)

        second = FakeSession(branch_sha="sha2", contents=contents, file_bodies={"https://raw/status": '{"n": 2}'})
        count = sync.sync(conn, second)

        assert count == 1
        rows = conn.execute("SELECT * FROM scout_data_files").fetchall()
        assert len(rows) == 1
        assert rows[0]["content"] == '{"n": 2}'
        assert rows[0]["commit_sha"] == "sha2"

    def test_no_json_files_on_the_branch_is_not_an_error(self):
        conn = _fresh_conn()
        session = FakeSession(branch_sha="abc123", contents=[], file_bodies={})

        count = sync.sync(conn, session)

        assert count == 0


class TestMain:
    def test_reports_ok_and_exits_zero_on_success(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sync, "DB_PATH", tmp_path / "scout_data.db")
        monkeypatch.setattr(sync, "_build_session", lambda: FakeSession(branch_sha="abc123", contents=[], file_bodies={}))

        exit_code = sync.main()

        assert exit_code == 0
        assert "OK:" in capsys.readouterr().out

    def test_reports_fail_and_exits_nonzero_on_request_error(self, monkeypatch, tmp_path, capsys):
        import requests

        monkeypatch.setattr(sync, "DB_PATH", tmp_path / "scout_data.db")

        class RaisingSession:
            def get(self, *args, **kwargs):
                raise requests.ConnectionError("no route to host")

        monkeypatch.setattr(sync, "_build_session", RaisingSession)

        exit_code = sync.main()

        assert exit_code == 1
        assert "FAIL:" in capsys.readouterr().out


class TestApplyMigrations:
    def test_running_twice_does_not_reapply_or_error(self):
        conn = _fresh_conn()

        db_schema.apply_migrations(conn)

        applied = conn.execute("SELECT version FROM schema_migrations").fetchall()
        assert len(applied) == 1
