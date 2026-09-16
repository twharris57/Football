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

import requests

from scout_api import db_schema, sync

from tests.scout_api_helpers import valid_finding_payload as _valid_finding_payload


class FakeResponse:
    def __init__(self, payload=None, text=None, status_code=200):
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload)
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error", response=self)

    def json(self):
        return self._payload


class FakeSession:
    """Dispatches GitHub API calls by URL, matching sync.py's own request shapes."""

    def __init__(
        self,
        branch_sha: str,
        contents: list[dict],
        file_bodies: dict[str, str],
        branch_status: int = 200,
    ):
        self.branch_sha = branch_sha
        self.contents = contents
        self.file_bodies = file_bodies
        self.branch_status = branch_status
        self.calls: list[str] = []
        self.headers_by_call: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        self.headers_by_call.append(headers or {})
        if url == f"{sync.GITHUB_API_BASE}/repos/{sync.REPO}/branches/{sync.BRANCH}":
            return FakeResponse({"commit": {"sha": self.branch_sha}}, status_code=self.branch_status)
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

    def test_removes_rows_for_files_no_longer_on_the_branch(self):
        conn = _fresh_conn()
        contents = [
            {"type": "file", "name": "a.json", "path": "scout-data/a.json", "download_url": "https://raw/a"},
            {"type": "file", "name": "b.json", "path": "scout-data/b.json", "download_url": "https://raw/b"},
        ]
        first = FakeSession(
            branch_sha="sha1", contents=contents, file_bodies={"https://raw/a": '{"n": 1}', "https://raw/b": '{"n": 2}'}
        )
        sync.sync(conn, first)

        contents_after_rename = [
            {"type": "file", "name": "a.json", "path": "scout-data/a.json", "download_url": "https://raw/a"},
        ]
        second = FakeSession(branch_sha="sha2", contents=contents_after_rename, file_bodies={"https://raw/a": '{"n": 1}'})
        count = sync.sync(conn, second)

        assert count == 1
        paths = {row["path"] for row in conn.execute("SELECT path FROM scout_data_files").fetchall()}
        assert paths == {"scout-data/a.json"}

    def test_raises_on_malformed_json_content(self):
        conn = _fresh_conn()
        contents = [
            {"type": "file", "name": "bad.json", "path": "scout-data/bad.json", "download_url": "https://raw/bad"},
        ]
        session = FakeSession(branch_sha="abc123", contents=contents, file_bodies={"https://raw/bad": "{not valid json"})

        try:
            sync.sync(conn, session)
            raise AssertionError("expected ValueError for malformed JSON content")
        except ValueError as exc:
            assert "bad.json" in str(exc)

        assert conn.execute("SELECT COUNT(*) FROM scout_data_files").fetchone()[0] == 0

    def test_file_downloads_include_auth_headers_when_token_set(self, monkeypatch):
        monkeypatch.setenv("SCOUT_DATA_GITHUB_TOKEN", "test-token")
        conn = _fresh_conn()
        contents = [
            {"type": "file", "name": "status.json", "path": "scout-data/status.json", "download_url": "https://raw/status"},
        ]
        session = FakeSession(branch_sha="abc123", contents=contents, file_bodies={"https://raw/status": '{"ok": true}'})

        sync.sync(conn, session)

        file_download_headers = session.headers_by_call[session.calls.index("https://raw/status")]
        assert file_download_headers.get("Authorization") == "Bearer test-token"


class TestFetchDataFiles:
    def test_raises_when_listing_may_be_truncated(self):
        contents = [
            {"type": "file", "name": f"f{i}.json", "path": f"scout-data/f{i}.json", "download_url": f"https://raw/{i}"}
            for i in range(sync.GITHUB_CONTENTS_PAGE_LIMIT)
        ]
        session = FakeSession(branch_sha="abc123", contents=contents, file_bodies={})

        try:
            sync.fetch_data_files(session, ref="abc123")
            raise AssertionError("expected RuntimeError for a possibly-truncated listing")
        except RuntimeError as exc:
            assert "truncated" in str(exc)


class TestMain:
    def test_reports_ok_and_exits_zero_on_success(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sync, "DB_PATH", tmp_path / "scout_data.db")
        monkeypatch.setattr(sync, "_build_session", lambda: FakeSession(branch_sha="abc123", contents=[], file_bodies={}))

        exit_code = sync.main()

        assert exit_code == 0
        assert "OK:" in capsys.readouterr().out

    def test_reports_fail_and_exits_nonzero_on_request_error(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sync, "DB_PATH", tmp_path / "scout_data.db")

        class RaisingSession:
            def get(self, *args, **kwargs):
                raise requests.ConnectionError("no route to host")

        monkeypatch.setattr(sync, "_build_session", RaisingSession)

        exit_code = sync.main()

        output = capsys.readouterr().out
        assert exit_code == 1
        assert "FAIL: could not sync scout-data from GitHub" in output

    def test_reports_fail_with_an_ingest_specific_message_on_a_malformed_finding(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sync, "DB_PATH", tmp_path / "scout_data.db")
        contents = [
            {
                "type": "file",
                "name": "finding_bad.json",
                "path": "scout-data/finding_bad.json",
                "download_url": "https://raw/finding_bad",
            },
        ]
        bad_finding = json.dumps(_valid_finding_payload(category="not_a_category"))
        monkeypatch.setattr(
            sync,
            "_build_session",
            lambda: FakeSession(branch_sha="abc123", contents=contents, file_bodies={"https://raw/finding_bad": bad_finding}),
        )

        exit_code = sync.main()

        output = capsys.readouterr().out
        assert exit_code == 1
        assert "FAIL: could not ingest findings into the local mirror" in output
        # The prior sync step (writing scout_data_files) must have succeeded
        # and been committed even though the later ingest step failed - the
        # two phases are separate transactions, not one all-or-nothing unit.
        conn = sync.connect(str(tmp_path / "scout_data.db"))
        assert conn.execute("SELECT COUNT(*) FROM scout_data_files").fetchone()[0] == 1
        conn.close()

    def test_reports_fail_and_exits_nonzero_on_http_error_status(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sync, "DB_PATH", tmp_path / "scout_data.db")
        monkeypatch.setattr(
            sync,
            "_build_session",
            lambda: FakeSession(branch_sha="abc123", contents=[], file_bodies={}, branch_status=403),
        )

        exit_code = sync.main()

        assert exit_code == 1
        assert "FAIL:" in capsys.readouterr().out

    def test_reports_fail_and_exits_nonzero_on_malformed_github_response(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sync, "DB_PATH", tmp_path / "scout_data.db")

        class MissingKeySession:
            def get(self, url, params=None, headers=None, timeout=None):
                if url == f"{sync.GITHUB_API_BASE}/repos/{sync.REPO}/branches/{sync.BRANCH}":
                    return FakeResponse({"commit": {}})
                raise AssertionError(f"unexpected URL requested: {url}")

        monkeypatch.setattr(sync, "_build_session", MissingKeySession)

        exit_code = sync.main()

        assert exit_code == 1
        assert "FAIL:" in capsys.readouterr().out


class TestApplyMigrations:
    def test_running_twice_does_not_reapply_or_error(self):
        conn = _fresh_conn()

        db_schema.apply_migrations(conn)

        applied = conn.execute("SELECT version FROM schema_migrations").fetchall()
        # Computed from the migrations directory rather than hardcoded, so
        # adding a future migration doesn't silently re-break this count.
        assert len(applied) == len(list(db_schema.MIGRATIONS_DIR.glob("*.sql")))


def _insert_data_file(conn, path, content, commit_sha="abc123", synced_at="2026-09-13T08:00:00+00:00"):
    conn.execute(
        "INSERT INTO scout_data_files (path, content, commit_sha, synced_at) VALUES (?, ?, ?, ?)",
        (path, content, commit_sha, synced_at),
    )


class TestIngestFindings:
    def test_ingests_a_well_formed_finding(self):
        conn = _fresh_conn()
        _insert_data_file(conn, "scout-data/finding_a.json", json.dumps(_valid_finding_payload()))

        count = sync.ingest_findings(conn)

        assert count == 1
        row = conn.execute("SELECT * FROM scout_findings WHERE path = ?", ("scout-data/finding_a.json",)).fetchone()
        assert row["player_id"] == "4046"
        assert row["category"] == "injury"

    def test_skips_files_that_are_not_findings(self):
        conn = _fresh_conn()
        _insert_data_file(conn, "scout-data/status.json", json.dumps({"ok": True}))

        count = sync.ingest_findings(conn)

        assert count == 0
        assert conn.execute("SELECT COUNT(*) FROM scout_findings").fetchone()[0] == 0

    def test_raises_on_a_malformed_finding_and_writes_nothing(self):
        conn = _fresh_conn()
        _insert_data_file(
            conn, "scout-data/finding_bad.json", json.dumps(_valid_finding_payload(category="not_a_category"))
        )

        try:
            sync.ingest_findings(conn)
            raise AssertionError("expected ValueError for a malformed finding")
        except ValueError as exc:
            assert "category" in str(exc)

        assert conn.execute("SELECT COUNT(*) FROM scout_findings").fetchone()[0] == 0

    def test_removes_findings_for_files_no_longer_present(self):
        conn = _fresh_conn()
        _insert_data_file(conn, "scout-data/finding_a.json", json.dumps(_valid_finding_payload()))
        sync.ingest_findings(conn)

        conn.execute("DELETE FROM scout_data_files WHERE path = ?", ("scout-data/finding_a.json",))
        count = sync.ingest_findings(conn)

        assert count == 0
        assert conn.execute("SELECT COUNT(*) FROM scout_findings").fetchone()[0] == 0

    def test_reingesting_updates_the_existing_row_rather_than_duplicating(self):
        conn = _fresh_conn()
        _insert_data_file(conn, "scout-data/finding_a.json", json.dumps(_valid_finding_payload(confidence="low")))
        sync.ingest_findings(conn)

        conn.execute(
            "UPDATE scout_data_files SET content = ? WHERE path = ?",
            (json.dumps(_valid_finding_payload(confidence="high")), "scout-data/finding_a.json"),
        )
        count = sync.ingest_findings(conn)

        assert count == 1
        rows = conn.execute("SELECT * FROM scout_findings").fetchall()
        assert len(rows) == 1
        assert rows[0]["confidence"] == "high"
