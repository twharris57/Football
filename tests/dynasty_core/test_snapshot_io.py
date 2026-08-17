"""Tests for dynasty_core.snapshot_io."""

from __future__ import annotations

import json

import pytest
from dynasty_core.snapshot_io import LoadedSnapshot, load_or_seed, write_if_changed


class TestLoadOrSeed:
    def test_returns_default_unstamped_when_file_does_not_exist(self, tmp_path):
        path = tmp_path / "missing.json"

        assert load_or_seed(path, {"a": 1}, schema_version=1) == LoadedSnapshot({"a": 1}, needs_rewrite=False)

    def test_returns_real_content_with_stamp_stripped_when_version_matches(self, tmp_path):
        path = tmp_path / "present.json"
        path.write_text(json.dumps({"a": 2, "schema_version": 1}), encoding="utf-8")

        assert load_or_seed(path, {"a": 1}, schema_version=1) == LoadedSnapshot({"a": 2}, needs_rewrite=False)

    def test_treats_a_file_with_no_stamp_at_all_as_version_zero(self, tmp_path):
        # Every real snapshot file on disk predates this mechanism - must
        # load cleanly, not raise, the first time it's read under it.
        path = tmp_path / "unstamped.json"
        path.write_text(json.dumps({"a": 3}), encoding="utf-8")

        loaded = load_or_seed(path, {"a": 1}, schema_version=1, migrations={0: lambda d: d})

        assert loaded == LoadedSnapshot({"a": 3}, needs_rewrite=True)

    def test_applies_a_single_migration_and_flags_needs_rewrite(self, tmp_path):
        path = tmp_path / "v0.json"
        path.write_text(json.dumps({"old_field": 5, "schema_version": 0}), encoding="utf-8")

        loaded = load_or_seed(
            path, {}, schema_version=1, migrations={0: lambda d: {"new_field": d["old_field"] * 2}}
        )

        assert loaded == LoadedSnapshot({"new_field": 10}, needs_rewrite=True)

    def test_applies_a_chain_of_migrations_in_sequence(self, tmp_path):
        path = tmp_path / "v0.json"
        path.write_text(json.dumps({"n": 1, "schema_version": 0}), encoding="utf-8")

        migrations = {
            0: lambda d: {"n": d["n"] + 10},
            1: lambda d: {"n": d["n"] + 100},
        }
        loaded = load_or_seed(path, {}, schema_version=2, migrations=migrations)

        assert loaded == LoadedSnapshot({"n": 111}, needs_rewrite=True)

    def test_no_rewrite_needed_when_stored_version_already_matches(self, tmp_path):
        path = tmp_path / "current.json"
        path.write_text(json.dumps({"a": 1, "schema_version": 2}), encoding="utf-8")

        loaded = load_or_seed(path, {}, schema_version=2, migrations={0: lambda d: d, 1: lambda d: d})

        assert loaded.needs_rewrite is False

    def test_raises_when_a_migration_is_missing_from_the_chain(self, tmp_path):
        path = tmp_path / "v0.json"
        path.write_text(json.dumps({"a": 1, "schema_version": 0}), encoding="utf-8")

        with pytest.raises(ValueError, match="no migration registered"):
            load_or_seed(path, {}, schema_version=2, migrations={0: lambda d: d})  # missing 1 -> 2

    def test_raises_on_a_file_newer_than_the_running_code(self, tmp_path):
        path = tmp_path / "future.json"
        path.write_text(json.dumps({"a": 1, "schema_version": 5}), encoding="utf-8")

        with pytest.raises(ValueError, match="newer than this code"):
            load_or_seed(path, {}, schema_version=1)


class TestWriteIfChanged:
    def test_writes_and_stamps_schema_version_when_updated_differs_from_existing(self, tmp_path):
        path = tmp_path / "out.json"

        write_if_changed(path, {"a": 1}, {"a": 2}, schema_version=3)

        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2, "schema_version": 3}

    def test_skips_write_when_identical_and_not_forced(self, tmp_path):
        path = tmp_path / "out.json"

        write_if_changed(path, {"a": 1}, {"a": 1}, schema_version=1)

        assert not path.exists()

    def test_force_writes_even_when_content_is_identical(self, tmp_path):
        # A migrated file must be persisted at its new schema the moment
        # it's touched, even if the reconcile logic itself found nothing
        # new to record - otherwise it could sit indefinitely on disk at
        # an old/missing stamp despite being read correctly every time.
        path = tmp_path / "out.json"

        write_if_changed(path, {"a": 1}, {"a": 1}, schema_version=2, force=True)

        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "schema_version": 2}

    def test_creates_parent_directory_if_missing(self, tmp_path):
        path = tmp_path / "nested" / "out.json"

        write_if_changed(path, {}, {"a": 1}, schema_version=1)

        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "schema_version": 1}
