"""Tests for fantasycalc_api.py's retry/session config and on-disk cache TTL behavior.

No real network calls - `fantasycalc_api._session.get` is monkeypatched with
a fake response, matching testing.md's "mock only external services you do
not control" exception for a genuine third-party API boundary. Cache paths
are monkeypatched to a pytest tmp_path so tests never touch the real
`.cache/` directory.
"""

from __future__ import annotations

import json
import os
import time

import fantasycalc_api as fc


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


class TestBuildSession:
    """Same rationale as sleeper_api's session - draft day means everyone
    hits this API at once, so a transient hiccup must retry rather than
    becoming a hard failure, but only for GET."""

    def test_retries_only_transient_failure_statuses_on_get(self):
        session = fc._build_session()
        retry = session.get_adapter("https://api.fantasycalc.com").max_retries

        assert retry.total == 3
        assert retry.backoff_factor == 0.5
        assert retry.status_forcelist == (429, 500, 502, 503, 504)
        assert retry.allowed_methods == ("GET",)


class TestGetDynastyValuesCache:
    def test_fresh_cache_is_returned_without_hitting_the_network(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "fantasycalc_values_2_12_1.0.json"
        cache_path.write_text(json.dumps([{"value": 100}]), encoding="utf-8")
        monkeypatch.setattr(fc, "CACHE_DIR", tmp_path)

        def fail_if_called(*args, **kwargs):
            raise AssertionError("should not hit the network when the cache is fresh")

        monkeypatch.setattr(fc._session, "get", fail_if_called)

        result = fc.get_dynasty_values(num_qbs=2, num_teams=12, ppr=1.0)

        assert result == [{"value": 100}]

    def test_stale_cache_triggers_a_real_fetch_and_is_overwritten(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "fantasycalc_values_2_12_1.0.json"
        cache_path.write_text(json.dumps([{"value": 100}]), encoding="utf-8")
        old_mtime = time.time() - fc.VALUES_CACHE_TTL_SECONDS - 1
        os.utime(cache_path, (old_mtime, old_mtime))
        monkeypatch.setattr(fc, "CACHE_DIR", tmp_path)

        calls = []

        def fake_get(url, params=None, timeout=None, **kwargs):
            calls.append(params)
            return FakeResponse([{"value": 200}])

        monkeypatch.setattr(fc._session, "get", fake_get)

        result = fc.get_dynasty_values(num_qbs=2, num_teams=12, ppr=1.0)

        assert result == [{"value": 200}]
        assert len(calls) == 1
        assert json.loads(cache_path.read_text(encoding="utf-8")) == [{"value": 200}]

    def test_force_refresh_bypasses_even_a_fresh_cache(self, monkeypatch, tmp_path):
        cache_path = tmp_path / "fantasycalc_values_2_12_1.0.json"
        cache_path.write_text(json.dumps([{"value": 100}]), encoding="utf-8")
        monkeypatch.setattr(fc, "CACHE_DIR", tmp_path)

        calls = []

        def fake_get(url, params=None, timeout=None, **kwargs):
            calls.append(params)
            return FakeResponse([{"value": 200}])

        monkeypatch.setattr(fc._session, "get", fake_get)

        result = fc.get_dynasty_values(num_qbs=2, num_teams=12, ppr=1.0, force_refresh=True)

        assert result == [{"value": 200}]
        assert len(calls) == 1

    def test_different_league_configs_use_different_cache_keys(self, monkeypatch, tmp_path):
        # A superflex (num_qbs=2) and single-QB (num_qbs=1) league must never
        # share a cached value - QB scarcity materially changes value.
        monkeypatch.setattr(fc, "CACHE_DIR", tmp_path)

        calls = []

        def fake_get(url, params=None, timeout=None, **kwargs):
            calls.append(dict(params))
            return FakeResponse([{"value": params["numQbs"]}])

        monkeypatch.setattr(fc._session, "get", fake_get)

        superflex = fc.get_dynasty_values(num_qbs=2, num_teams=12, ppr=1.0)
        single_qb = fc.get_dynasty_values(num_qbs=1, num_teams=12, ppr=1.0)

        assert superflex == [{"value": 2}]
        assert single_qb == [{"value": 1}]
        assert len(calls) == 2  # neither hit the other's cache file
