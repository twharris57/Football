"""Tests for dynasty/scout_api/schema_validation.py's shared strict-field
validators, used by both finding_schema.py and run_record_schema.py.
"""

from __future__ import annotations

from scout_api import schema_validation


class TestRequireNonemptyStr:
    def test_returns_the_value_when_present(self):
        assert schema_validation.require_nonempty_str({"x": "hello"}, "x") == "hello"

    def test_rejects_an_empty_string(self):
        try:
            schema_validation.require_nonempty_str({"x": ""}, "x")
            raise AssertionError("expected ValueError for an empty string")
        except ValueError as exc:
            assert "x" in str(exc)

    def test_rejects_a_non_string(self):
        try:
            schema_validation.require_nonempty_str({"x": 5}, "x")
            raise AssertionError("expected ValueError for a non-string")
        except ValueError as exc:
            assert "x" in str(exc)


class TestRequireNullableStr:
    def test_returns_none_for_null(self):
        assert schema_validation.require_nullable_str({"x": None}, "x") is None

    def test_returns_the_value_when_present(self):
        assert schema_validation.require_nullable_str({"x": "hello"}, "x") == "hello"

    def test_rejects_an_empty_string(self):
        # A nullable field is null-or-a-real-value - "" as a third,
        # ambiguous state would let two downstream checks (`is None` vs.
        # truthy) disagree about the same stored value.
        try:
            schema_validation.require_nullable_str({"x": ""}, "x")
            raise AssertionError("expected ValueError for an empty string")
        except ValueError as exc:
            assert "x" in str(exc)

    def test_rejects_a_non_string_non_null_value(self):
        try:
            schema_validation.require_nullable_str({"x": 5}, "x")
            raise AssertionError("expected ValueError for a non-string, non-null value")
        except ValueError as exc:
            assert "x" in str(exc)


class TestRequireIso8601:
    def test_returns_the_value_for_a_tz_aware_timestamp(self):
        value = "2026-09-16T01:00:00+00:00"
        assert schema_validation.require_iso8601({"x": value}, "x") == value

    def test_rejects_a_non_iso_string(self):
        try:
            schema_validation.require_iso8601({"x": "not a date"}, "x")
            raise AssertionError("expected ValueError for a non-ISO8601 string")
        except ValueError as exc:
            assert "x" in str(exc)

    def test_rejects_a_timezone_naive_timestamp(self):
        try:
            schema_validation.require_iso8601({"x": "2026-09-16T01:00:00"}, "x")
            raise AssertionError("expected ValueError for a timezone-naive timestamp")
        except ValueError as exc:
            assert "timezone-naive" in str(exc)

    def test_rejects_an_empty_string(self):
        try:
            schema_validation.require_iso8601({"x": ""}, "x")
            raise AssertionError("expected ValueError for an empty string")
        except ValueError as exc:
            assert "x" in str(exc)


class TestRequireExactKeys:
    def test_accepts_an_exact_key_match(self):
        schema_validation.require_exact_keys({"a": 1, "b": 2}, frozenset({"a", "b"}), "thing")

    def test_rejects_a_missing_key(self):
        try:
            schema_validation.require_exact_keys({"a": 1}, frozenset({"a", "b"}), "thing")
            raise AssertionError("expected ValueError for a missing key")
        except ValueError as exc:
            assert "thing" in str(exc) and "missing" in str(exc) and "unexpected" not in str(exc)

    def test_rejects_an_unexpected_key(self):
        try:
            schema_validation.require_exact_keys({"a": 1, "b": 2, "c": 3}, frozenset({"a", "b"}), "thing")
            raise AssertionError("expected ValueError for an unexpected key")
        except ValueError as exc:
            assert "thing" in str(exc) and "unexpected" in str(exc) and "missing" not in str(exc)

    def test_reports_both_missing_and_unexpected_keys_together(self):
        try:
            schema_validation.require_exact_keys({"a": 1, "c": 3}, frozenset({"a", "b"}), "thing")
            raise AssertionError("expected ValueError for both a missing and an unexpected key")
        except ValueError as exc:
            message = str(exc)
            assert "missing" in message and "'b'" in message
            assert "unexpected" in message and "'c'" in message
