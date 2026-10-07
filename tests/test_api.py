"""Tests for dynasty.api -- routes served through Starlette's test client against a real SQLite file."""

from __future__ import annotations

from pathlib import Path

import pytest
from starlette.applications import Starlette
from streamlit.starlette import App
from starlette.testclient import TestClient

import api
import trade_block_store

TOKEN = "test-token"


@pytest.fixture
def db_path(tmp_path):
    """A store file emptied of the seed migration's rows."""
    path = tmp_path / "dynasty_data" / "trade_block.db"
    path.parent.mkdir()
    conn = trade_block_store.connect(str(path))
    with conn:
        conn.execute("DELETE FROM trade_block")
    conn.close()
    return path


def _client(db_path, token: str | None = TOKEN) -> TestClient:
    return TestClient(Starlette(routes=api.routes(db_path, token)))


def _auth(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_routes_mount_in_streamlit_app_without_reserved_conflicts(db_path):
    script = Path(__file__).parent.parent / "dynasty" / "streamlit_app.py"
    App(script, routes=api.routes(db_path, TOKEN))


class TestHealth:
    def test_health_without_token_returns_ok(self, db_path):
        response = _client(db_path).get("/api/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_health_with_no_token_configured_still_returns_ok(self, db_path):
        assert _client(db_path, token=None).get("/api/health").status_code == 200


class TestTradeBlockAuth:
    def test_trade_block_missing_header_returns_401(self, db_path):
        assert _client(db_path).get("/api/trade-block").status_code == 401

    def test_trade_block_wrong_token_returns_401(self, db_path):
        response = _client(db_path).get("/api/trade-block", headers=_auth("wrong"))

        assert response.status_code == 401

    def test_trade_block_bare_token_without_bearer_scheme_returns_401(self, db_path):
        response = _client(db_path).get("/api/trade-block", headers={"Authorization": TOKEN})

        assert response.status_code == 401

    @pytest.mark.parametrize("token", [None, ""])
    def test_trade_block_no_token_configured_returns_503(self, db_path, token):
        response = _client(db_path, token=token).get("/api/trade-block", headers=_auth())

        assert response.status_code == 503

    def test_trade_block_post_returns_405(self, db_path):
        assert _client(db_path).post("/api/trade-block", headers=_auth()).status_code == 405


class TestTradeBlockData:
    def test_trade_block_empty_store_returns_empty_list(self, db_path):
        response = _client(db_path).get("/api/trade-block", headers=_auth())

        assert response.status_code == 200
        assert response.json() == {"entries": []}

    def test_trade_block_returns_entries_newest_first(self, db_path):
        conn = trade_block_store.connect(str(db_path))
        trade_block_store.add_trade_block_entry(conn, "5927", 2, "2026-09-20")
        trade_block_store.add_trade_block_entry(conn, "7523", 1, "2026-09-22")
        conn.close()

        response = _client(db_path).get("/api/trade-block", headers=_auth())

        assert response.json() == {
            "entries": [
                {"sleeper_id": "7523", "roster_id": 1, "added_date": "2026-09-22"},
                {"sleeper_id": "5927", "roster_id": 2, "added_date": "2026-09-20"},
            ]
        }
