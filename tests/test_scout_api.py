"""Tests for dynasty/scout_api's proof-of-concept endpoints.

`SCOUT_API_TOKEN` is set before import - the module raises at import time
if it's unset (see app.py), so it has to exist before pytest even
collects this file, not inside a per-test fixture.
"""

from __future__ import annotations

import os

os.environ.setdefault("SCOUT_API_TOKEN", "test-token")

from fastapi.testclient import TestClient  # noqa: E402
from scout_api.app import app  # noqa: E402

client = TestClient(app)


class TestHealth:
    def test_health_requires_no_auth(self):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestPing:
    def test_rejects_missing_token(self):
        response = client.get("/ping")

        assert response.status_code == 401

    def test_rejects_wrong_token(self):
        response = client.get("/ping", headers={"X-Scout-Token": "not-the-real-token"})

        assert response.status_code == 401

    def test_accepts_correct_token(self):
        response = client.get("/ping", headers={"X-Scout-Token": "test-token"})

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["service"] == "dynasty-scout-api"
