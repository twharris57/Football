"""JSON API for the cloud scout, served beside the Streamlit UI under `/api`."""

from __future__ import annotations

import hmac
import logging
from dataclasses import asdict
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

import trade_block_store

logger = logging.getLogger(__name__)


def _authorize(request: Request, token: str | None) -> JSONResponse | None:
    """Return an error response unless the request carries the configured bearer token."""
    if not token:
        return JSONResponse({"error": "API token not configured"}, status_code=503)
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(supplied.encode(), token.encode()):
        logger.warning("API request rejected: bad or missing token", extra={"path": request.url.path})
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


def routes(db_path: Path, token: str | None) -> list[Route]:
    """Build the `/api` routes. With no `token`, protected routes answer 503 rather than run open."""
    if not token:
        logger.warning("SCOUT_API_TOKEN is not set; protected API routes will answer 503")

    def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    def trade_block(request: Request) -> JSONResponse:
        if error := _authorize(request, token):
            return error
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = trade_block_store.connect(str(db_path))
        try:
            entries = trade_block_store.get_trade_block(conn)
        finally:
            conn.close()
        ordered = sorted(entries, key=lambda e: (e.added_date, e.sleeper_id), reverse=True)
        return JSONResponse({"entries": [asdict(e) for e in ordered]})

    return [
        Route("/api/health", health, methods=["GET"]),
        Route("/api/trade-block", trade_block, methods=["GET"]),
    ]
