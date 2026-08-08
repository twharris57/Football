"""Tests for dynasty_core.snapshot_io."""

from __future__ import annotations

import json

from dynasty_core.snapshot_io import load_or_seed, write_if_changed


class TestLoadOrSeed:
    def test_returns_default_when_file_does_not_exist(self, tmp_path):
        path = tmp_path / "missing.json"

        assert load_or_seed(path, {"a": 1}) == {"a": 1}

    def test_returns_real_content_when_file_exists(self, tmp_path):
        path = tmp_path / "present.json"
        path.write_text(json.dumps({"a": 2}), encoding="utf-8")

        assert load_or_seed(path, {"a": 1}) == {"a": 2}


class TestWriteIfChanged:
    def test_writes_when_updated_differs_from_existing(self, tmp_path):
        path = tmp_path / "out.json"

        write_if_changed(path, {"a": 1}, {"a": 2})

        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}

    def test_skips_write_when_identical(self, tmp_path):
        path = tmp_path / "out.json"

        write_if_changed(path, {"a": 1}, {"a": 1})

        assert not path.exists()

    def test_creates_parent_directory_if_missing(self, tmp_path):
        path = tmp_path / "nested" / "out.json"

        write_if_changed(path, {}, {"a": 1})

        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
