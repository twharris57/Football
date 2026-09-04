"""FastAPI app for the scout API's proof-of-concept slice.

`/health` is unauthenticated (container/orchestrator liveness only, no
scout data behind it). `/ping` requires `SCOUT_API_TOKEN` via the
`X-Scout-Token` header - it's the endpoint that actually proves the
cloud routine can reach *and authenticate against* this service, which
`/health` alone can't demonstrate.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException

_VERSION = (Path(__file__).parent / "VERSION").read_text(encoding="utf-8").strip()
_GIT_SHA = os.environ.get("GIT_SHA", "dev")

_API_TOKEN = os.environ.get("SCOUT_API_TOKEN")
if not _API_TOKEN:
    # Fail loudly at startup rather than silently run an "authenticated"
    # endpoint with no real secret to check against - the container should
    # crash-loop and fail its healthcheck, not quietly accept every request.
    raise RuntimeError("SCOUT_API_TOKEN must be set - refusing to start with no real auth secret")

app = FastAPI(title="Dynasty Scout API", version=_VERSION)


def _require_token(x_scout_token: str | None = Header(default=None)) -> None:
    if not x_scout_token or not secrets.compare_digest(x_scout_token, _API_TOKEN):
        raise HTTPException(status_code=401, detail="invalid or missing token")


@app.get("/health")
def health() -> dict[str, str]:
    """Unauthenticated liveness check."""
    return {"status": "ok"}


@app.get("/ping", dependencies=[Depends(_require_token)])
def ping() -> dict[str, str]:
    """Authenticated reachability check - network path and auth both working."""
    return {"status": "ok", "service": "dynasty-scout-api", "version": _VERSION, "git_sha": _GIT_SHA}
