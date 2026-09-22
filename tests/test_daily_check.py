"""Tests for dynasty/scripts/daily_check.py - the automated daily scout's
cloud-routine entry point (.claude/PROJECT_PLAN_DYNASTY.md's "Automated
daily scout" section).

`dynasty_core.gather_state` is monkeypatched with a synthetic result -
this only exercises daily_check.py's own extraction/reporting logic, not
gather_state()'s own (already covered by tests/dynasty_core/'s suite), so
no real Sleeper/FantasyCalc calls happen here.
"""

from __future__ import annotations

import dynasty_core as dc
from scripts import daily_check


def _fake_state() -> dict:
    return {
        "league": {"season": "2026", "settings": {"leg": 3}},
        "attention_digest": {"pickup_alerts": ["Add Some Player - would add +2.1 to your lineup"]},
        "data_warnings": ["Bye week data unavailable this refresh"],
    }


class TestRun:
    def test_extracts_only_the_json_serializable_signal_fields(self, monkeypatch):
        captured_args = {}

        def fake_gather_state(league_id, username, force_full_refresh, force_scoring_refresh):
            captured_args["league_id"] = league_id
            captured_args["username"] = username
            captured_args["force_full_refresh"] = force_full_refresh
            captured_args["force_scoring_refresh"] = force_scoring_refresh
            return _fake_state()

        monkeypatch.setattr(dc, "gather_state", fake_gather_state)

        result = daily_check.run("league123", "someuser")

        assert result == {
            "league_id": "league123",
            "season": "2026",
            "current_week": 3,
            "attention_digest": {"pickup_alerts": ["Add Some Player - would add +2.1 to your lineup"]},
            "data_warnings": ["Bye week data unavailable this refresh"],
        }
        assert captured_args == {
            "league_id": "league123",
            "username": "someuser",
            "force_full_refresh": False,
            "force_scoring_refresh": False,
        }


class TestMain:
    def test_reports_ok_and_exits_zero_on_success(self, monkeypatch, capsys):
        monkeypatch.setattr(dc, "gather_state", lambda *a, **k: _fake_state())

        exit_code = daily_check.main()

        assert exit_code == 0
        assert "OK:" in capsys.readouterr().out

    def test_reports_fail_and_exits_nonzero_on_any_error(self, monkeypatch, capsys):
        def raising_gather_state(*args, **kwargs):
            raise KeyError("roster_positions")

        monkeypatch.setattr(dc, "gather_state", raising_gather_state)

        exit_code = daily_check.main()

        assert exit_code == 1
        assert "FAIL:" in capsys.readouterr().out

    def test_uses_env_vars_when_set(self, monkeypatch, capsys):
        monkeypatch.setenv("DYNASTY_LEAGUE_ID", "env-league")
        monkeypatch.setenv("DYNASTY_USERNAME", "env-user")
        captured = {}

        def fake_gather_state(league_id, username, force_full_refresh, force_scoring_refresh):
            captured["league_id"] = league_id
            captured["username"] = username
            return _fake_state()

        monkeypatch.setattr(dc, "gather_state", fake_gather_state)

        daily_check.main()

        assert captured == {"league_id": "env-league", "username": "env-user"}

    def test_falls_back_to_defaults_when_env_vars_unset(self, monkeypatch, capsys):
        monkeypatch.delenv("DYNASTY_LEAGUE_ID", raising=False)
        monkeypatch.delenv("DYNASTY_USERNAME", raising=False)
        captured = {}

        def fake_gather_state(league_id, username, force_full_refresh, force_scoring_refresh):
            captured["league_id"] = league_id
            captured["username"] = username
            return _fake_state()

        monkeypatch.setattr(dc, "gather_state", fake_gather_state)

        daily_check.main()

        assert captured == {"league_id": dc.DEFAULT_LEAGUE_ID, "username": dc.DEFAULT_USERNAME}
