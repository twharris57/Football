"""Tests for dynasty/scout_api/finding_schema.py's SC-2 templated finding
schema: parsing/validation and the JSON round-trip.
"""

from __future__ import annotations

import json

from scout_api import finding_schema

from tests.scout_api_helpers import valid_finding_payload as _valid_payload


class TestParseFinding:
    def test_parses_a_well_formed_finding(self):
        finding = finding_schema.parse_finding(json.dumps(_valid_payload()))

        assert finding.player_id == "4046"
        assert finding.category == "injury"
        assert finding.confidence == "medium"

    def test_round_trips_through_finding_to_json(self):
        original = finding_schema.parse_finding(json.dumps(_valid_payload()))

        reparsed = finding_schema.parse_finding(finding_schema.finding_to_json(original))

        assert reparsed == original

    def test_rejects_a_missing_field(self):
        payload = _valid_payload()
        del payload["source"]

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for a missing field")
        except ValueError as exc:
            assert "missing" in str(exc)

    def test_rejects_an_unexpected_field(self):
        payload = _valid_payload(extra_field="not part of the schema")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for an unexpected field")
        except ValueError as exc:
            assert "unexpected" in str(exc)

    def test_rejects_an_invalid_category(self):
        payload = _valid_payload(category="not_a_real_category")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for an invalid category")
        except ValueError as exc:
            assert "category" in str(exc)

    def test_rejects_an_invalid_confidence(self):
        payload = _valid_payload(confidence="extremely-sure")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for an invalid confidence")
        except ValueError as exc:
            assert "confidence" in str(exc)

    def test_rejects_a_non_iso_observed_at(self):
        payload = _valid_payload(observed_at="last Tuesday")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-ISO8601 observed_at")
        except ValueError as exc:
            assert "observed_at" in str(exc)

    def test_rejects_a_non_iso_created_at(self):
        payload = _valid_payload(created_at="not a date")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-ISO8601 created_at")
        except ValueError as exc:
            assert "created_at" in str(exc)

    def test_rejects_a_timezone_naive_observed_at(self):
        payload = _valid_payload(observed_at="2026-09-10T12:00:00")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for a timezone-naive observed_at")
        except ValueError as exc:
            assert "observed_at" in str(exc) and "timezone-naive" in str(exc)

    def test_rejects_a_timezone_naive_created_at(self):
        payload = _valid_payload(created_at="2026-09-13T08:00:00")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for a timezone-naive created_at")
        except ValueError as exc:
            assert "created_at" in str(exc) and "timezone-naive" in str(exc)

    def test_rejects_an_empty_summary(self):
        payload = _valid_payload(summary="")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for an empty summary")
        except ValueError as exc:
            assert "summary" in str(exc)

    def test_rejects_a_summary_over_the_length_cap(self):
        payload = _valid_payload(summary="x" * (finding_schema.SUMMARY_MAX_LENGTH + 1))

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for an over-length summary")
        except ValueError as exc:
            assert "summary" in str(exc)

    def test_rejects_an_empty_player_id(self):
        payload = _valid_payload(player_id="")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for an empty player_id")
        except ValueError as exc:
            assert "player_id" in str(exc)

    def test_rejects_an_empty_source(self):
        payload = _valid_payload(source="")

        try:
            finding_schema.parse_finding(json.dumps(payload))
            raise AssertionError("expected ValueError for an empty source")
        except ValueError as exc:
            assert "source" in str(exc)

    def test_rejects_content_that_is_not_a_json_object(self):
        try:
            finding_schema.parse_finding(json.dumps(["not", "an", "object"]))
            raise AssertionError("expected ValueError for non-object content")
        except ValueError as exc:
            assert "JSON object" in str(exc)


class TestIsFindingPath:
    def test_true_for_a_real_scout_data_finding_path(self):
        assert finding_schema.is_finding_path("scout-data/finding_abc123.json") is True

    def test_false_for_a_non_finding_file_on_scout_data(self):
        assert finding_schema.is_finding_path("scout-data/status.json") is False

    def test_false_when_only_the_directory_matches_the_prefix(self):
        # Regression guard: is_finding_path must check the filename, not
        # the full path - every real path is "scout-data/..." so a naive
        # full-path prefix check would never distinguish anything.
        assert finding_schema.is_finding_path("scout-data/finding_dir/other.json") is False
