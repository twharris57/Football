"""Tests for sleeper_api.py's retry/session config and on-disk cache TTL behavior.

No real network calls - `sleeper_api._session.get` is monkeypatched with a
fake response, matching testing.md's "mock only external services you do
not control" exception for a genuine third-party API boundary. Cache paths
are monkeypatched to a pytest tmp_path so tests never touch the real
`.cache/` directory.
"""

from __future__ import annotations

import json
import os
import time

import sleeper_api


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


class TestBuildSession:
    """Draft day means everyone hits this API at once - a transient hiccup
    (connection error, 429, 5xx) must retry rather than becoming a hard
    failure, but only for GET (safe to retry; no risk of double-submitting
    a write)."""

    def test_retries_only_transient_failure_statuses_on_get(self):
        session = sleeper_api._build_session()
        retry = session.get_adapter("https://api.sleeper.app").max_retries

        assert retry.total == 3
        assert retry.backoff_factor == 0.5
        assert retry.status_forcelist == (429, 500, 502, 503, 504)
        assert retry.allowed_methods == ("GET",)

    def test_same_retry_adapter_mounted_for_http_and_https(self):
        session = sleeper_api._build_session()

        assert session.get_adapter("http://api.sleeper.app") is session.get_adapter("https://api.sleeper.app")


class TestGetPlayersCache:
    def test_fresh_cache_is_returned_without_hitting_the_network(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "players.json"
        cache_path.write_text(json.dumps({"p1": {"position": "WR"}}), encoding="utf-8")
        monkeypatch.setattr(sleeper_api, "PLAYERS_CACHE_PATH", cache_path)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("should not hit the network when the cache is fresh")

        monkeypatch.setattr(sleeper_api._session, "get", fail_if_called)

        assert sleeper_api.get_players() == {"p1": {"position": "WR"}}

    def test_stale_cache_triggers_a_real_fetch_and_is_overwritten(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "players.json"
        cache_path.write_text(json.dumps({"p1": {"position": "WR"}}), encoding="utf-8")
        old_mtime = time.time() - sleeper_api.PLAYERS_CACHE_TTL_SECONDS - 1
        os.utime(cache_path, (old_mtime, old_mtime))
        monkeypatch.setattr(sleeper_api, "PLAYERS_CACHE_PATH", cache_path)
        monkeypatch.setattr(sleeper_api, "CACHE_DIR", tmp_path)

        calls = []

        def fake_get(url, timeout=None, **kwargs):
            calls.append(url)
            return FakeResponse({"p2": {"position": "RB"}})

        monkeypatch.setattr(sleeper_api._session, "get", fake_get)

        result = sleeper_api.get_players()

        assert result == {"p2": {"position": "RB"}}
        assert len(calls) == 1
        assert json.loads(cache_path.read_text(encoding="utf-8")) == {"p2": {"position": "RB"}}

    def test_force_refresh_bypasses_even_a_fresh_cache(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "players.json"
        cache_path.write_text(json.dumps({"p1": {"position": "WR"}}), encoding="utf-8")
        monkeypatch.setattr(sleeper_api, "PLAYERS_CACHE_PATH", cache_path)
        monkeypatch.setattr(sleeper_api, "CACHE_DIR", tmp_path)

        calls = []

        def fake_get(url, timeout=None, **kwargs):
            calls.append(url)
            return FakeResponse({"p2": {"position": "RB"}})

        monkeypatch.setattr(sleeper_api._session, "get", fake_get)

        result = sleeper_api.get_players(force_refresh=True)

        assert result == {"p2": {"position": "RB"}}
        assert len(calls) == 1


class TestGetTransactionsCache:
    def test_fresh_cache_is_returned_without_hitting_the_network(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "transactions_league1_2026.json"
        cache_path.write_text(json.dumps([{"type": "waiver"}]), encoding="utf-8")
        monkeypatch.setattr(sleeper_api, "CACHE_DIR", tmp_path)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("should not hit the network when the cache is fresh")

        monkeypatch.setattr(sleeper_api._session, "get", fail_if_called)

        result = sleeper_api.get_transactions("league1", "2026", current_leg=3)

        assert result == [{"type": "waiver"}]

    def test_stale_cache_refetches_every_leg_from_1_through_current(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "transactions_league1_2026.json"
        cache_path.write_text(json.dumps([{"type": "waiver"}]), encoding="utf-8")
        old_mtime = time.time() - sleeper_api.TRANSACTIONS_CACHE_TTL_SECONDS - 1
        os.utime(cache_path, (old_mtime, old_mtime))
        monkeypatch.setattr(sleeper_api, "CACHE_DIR", tmp_path)

        requested_paths = []

        def fake_get(url, timeout=None, **kwargs):
            requested_paths.append(url)
            leg = url.rsplit("/", 1)[-1]
            return FakeResponse([{"type": "trade", "leg": leg}])

        monkeypatch.setattr(sleeper_api._session, "get", fake_get)

        result = sleeper_api.get_transactions("league1", "2026", current_leg=3)

        assert len(requested_paths) == 3
        assert [txn["leg"] for txn in result] == ["1", "2", "3"]


class TestGetWeeklyProjectionsCache:
    def test_force_refresh_bypasses_a_fresh_cache(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "projections_2026_5.json"
        cache_path.write_text(json.dumps({"p1": {"rec": 5.0}}), encoding="utf-8")
        monkeypatch.setattr(sleeper_api, "CACHE_DIR", tmp_path)

        calls = []

        def fake_get(url, timeout=None, **kwargs):
            calls.append(url)
            return FakeResponse({"p1": {"rec": 6.0}})

        monkeypatch.setattr(sleeper_api._session, "get", fake_get)

        result = sleeper_api.get_weekly_projections("2026", 5, force_refresh=True)

        assert result == {"p1": {"rec": 6.0}}
        assert len(calls) == 1
