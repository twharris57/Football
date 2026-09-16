"""Tests for dynasty/scout_api/run_record_schema.py's SC-4 run-record
schema: parsing/validation and the JSON round-trip.
"""

from __future__ import annotations

import json

from scout_api import run_record_schema

from tests.scout_api_helpers import valid_reviewed_item_payload, valid_run_record_payload


class TestParseRunRecord:
    def test_parses_a_well_formed_run_record(self):
        record = run_record_schema.parse_run_record(json.dumps(valid_run_record_payload()))

        assert record.run_date == "2026-09-16"
        assert record.notification_fired is True
        assert record.reflection is None
        assert len(record.items) == 1
        assert record.items[0].player_id == "4046"

    def test_round_trips_through_run_record_to_json(self):
        original = run_record_schema.parse_run_record(json.dumps(valid_run_record_payload()))

        reparsed = run_record_schema.parse_run_record(run_record_schema.run_record_to_json(original))

        assert reparsed == original

    def test_round_trips_a_populated_reflection(self):
        payload = valid_run_record_payload(
            reflection={
                "reviewed_at": "2026-09-20T01:00:00+00:00",
                "notes": "Surfaced injury update matched a real IR move two days later.",
                "issue_url": None,
            }
        )
        original = run_record_schema.parse_run_record(json.dumps(payload))

        reparsed = run_record_schema.parse_run_record(run_record_schema.run_record_to_json(original))

        assert reparsed == original
        assert reparsed.reflection.notes.startswith("Surfaced injury update")

    def test_accepts_zero_items_as_a_quiet_night(self):
        payload = valid_run_record_payload(items=[], notification_fired=False)

        record = run_record_schema.parse_run_record(json.dumps(payload))

        assert record.items == ()
        assert record.notification_fired is False

    def test_rejects_a_missing_field(self):
        payload = valid_run_record_payload()
        del payload["notification_fired"]

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a missing field")
        except ValueError as exc:
            assert "missing" in str(exc)

    def test_rejects_an_unexpected_field(self):
        payload = valid_run_record_payload(extra_field="not part of the schema")

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for an unexpected field")
        except ValueError as exc:
            assert "unexpected" in str(exc)

    def test_rejects_a_non_iso_date_run_date(self):
        payload = valid_run_record_payload(run_date="Sept 16 2026")

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-ISO-date run_date")
        except ValueError as exc:
            assert "run_date" in str(exc)

    def test_rejects_a_non_iso_generated_at(self):
        payload = valid_run_record_payload(generated_at="not a date")

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-ISO8601 generated_at")
        except ValueError as exc:
            assert "generated_at" in str(exc)

    def test_rejects_a_timezone_naive_generated_at(self):
        payload = valid_run_record_payload(generated_at="2026-09-17T01:00:00")

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a timezone-naive generated_at")
        except ValueError as exc:
            assert "generated_at" in str(exc) and "timezone-naive" in str(exc)

    def test_rejects_a_non_boolean_notification_fired(self):
        payload = valid_run_record_payload(notification_fired="yes")

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-boolean notification_fired")
        except ValueError as exc:
            assert "notification_fired" in str(exc)

    def test_rejects_items_that_is_not_a_list(self):
        payload = valid_run_record_payload(items={"not": "a list"})

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-list items")
        except ValueError as exc:
            assert "items" in str(exc)

    def test_rejects_content_that_is_not_a_json_object(self):
        try:
            run_record_schema.parse_run_record(json.dumps(["not", "an", "object"]))
            raise AssertionError("expected ValueError for non-object content")
        except ValueError as exc:
            assert "JSON object" in str(exc)


class TestParseReviewedItem:
    def test_rejects_an_item_missing_a_field(self):
        item = valid_reviewed_item_payload()
        del item["reason"]
        payload = valid_run_record_payload(items=[item])

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for an item missing a field")
        except ValueError as exc:
            assert "items[0]" in str(exc) and "missing" in str(exc)

    def test_rejects_an_invalid_category(self):
        payload = valid_run_record_payload(items=[valid_reviewed_item_payload(category="not_a_real_category")])

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for an invalid category")
        except ValueError as exc:
            assert "category" in str(exc)

    def test_rejects_an_invalid_verdict_lane(self):
        payload = valid_run_record_payload(items=[valid_reviewed_item_payload(verdict_lane="gut_feeling")])

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for an invalid verdict_lane")
        except ValueError as exc:
            assert "verdict_lane" in str(exc)

    def test_rejects_an_invalid_verdict(self):
        payload = valid_run_record_payload(items=[valid_reviewed_item_payload(verdict="maybe")])

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for an invalid verdict")
        except ValueError as exc:
            assert "verdict" in str(exc)

    def test_rejects_an_empty_reason(self):
        payload = valid_run_record_payload(items=[valid_reviewed_item_payload(reason="")])

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for an empty reason")
        except ValueError as exc:
            assert "reason" in str(exc)

    def test_rejects_a_reason_over_the_length_cap(self):
        payload = valid_run_record_payload(
            items=[valid_reviewed_item_payload(reason="x" * (run_record_schema.REASON_MAX_LENGTH + 1))]
        )

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for an over-length reason")
        except ValueError as exc:
            assert "reason" in str(exc)

    def test_accepts_a_non_null_source_path(self):
        payload = valid_run_record_payload(
            items=[valid_reviewed_item_payload(source_path="scout-data/finding_abc123.json")]
        )

        record = run_record_schema.parse_run_record(json.dumps(payload))

        assert record.items[0].source_path == "scout-data/finding_abc123.json"

    def test_rejects_a_non_string_non_null_source_path(self):
        payload = valid_run_record_payload(items=[valid_reviewed_item_payload(source_path=123)])

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-string source_path")
        except ValueError as exc:
            assert "source_path" in str(exc)


class TestParseReflection:
    def test_rejects_a_reflection_missing_a_field(self):
        payload = valid_run_record_payload(reflection={"reviewed_at": "2026-09-20T01:00:00+00:00", "notes": "x"})

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a reflection missing a field")
        except ValueError as exc:
            assert "reflection" in str(exc) and "missing" in str(exc)

    def test_rejects_a_non_iso_reflection_reviewed_at(self):
        payload = valid_run_record_payload(
            reflection={"reviewed_at": "not a date", "notes": "x", "issue_url": None}
        )

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-ISO8601 reflection.reviewed_at")
        except ValueError as exc:
            assert "reviewed_at" in str(exc)

    def test_rejects_an_empty_reflection_notes(self):
        payload = valid_run_record_payload(
            reflection={"reviewed_at": "2026-09-20T01:00:00+00:00", "notes": "", "issue_url": None}
        )

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for empty reflection.notes")
        except ValueError as exc:
            assert "notes" in str(exc)

    def test_rejects_reflection_notes_over_the_length_cap(self):
        payload = valid_run_record_payload(
            reflection={
                "reviewed_at": "2026-09-20T01:00:00+00:00",
                "notes": "x" * (run_record_schema.REFLECTION_NOTES_MAX_LENGTH + 1),
                "issue_url": None,
            }
        )

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for over-length reflection.notes")
        except ValueError as exc:
            assert "notes" in str(exc)

    def test_accepts_a_non_null_issue_url(self):
        payload = valid_run_record_payload(
            reflection={
                "reviewed_at": "2026-09-20T01:00:00+00:00",
                "notes": "Missed a drop that should have been flagged.",
                "issue_url": "https://github.com/twharris57/Football/issues/99",
            }
        )

        record = run_record_schema.parse_run_record(json.dumps(payload))

        assert record.reflection.issue_url == "https://github.com/twharris57/Football/issues/99"

    def test_rejects_reflection_that_is_not_an_object_or_null(self):
        payload = valid_run_record_payload(reflection="not an object")

        try:
            run_record_schema.parse_run_record(json.dumps(payload))
            raise AssertionError("expected ValueError for a non-object, non-null reflection")
        except ValueError as exc:
            assert "reflection" in str(exc)


class TestIsRunRecordPath:
    def test_true_for_a_real_scout_data_run_record_path(self):
        assert run_record_schema.is_run_record_path("scout-data/run_20260916.json") is True

    def test_false_for_a_non_run_record_file_on_scout_data(self):
        assert run_record_schema.is_run_record_path("scout-data/finding_abc123.json") is False

    def test_false_when_only_the_directory_matches_the_prefix(self):
        assert run_record_schema.is_run_record_path("scout-data/run_dir/other.json") is False
