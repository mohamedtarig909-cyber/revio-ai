"""Public, first-party page-view tracking.

The site pings this on page load. Deliberately tiny and forgiving: tracking must
never break a page or slow it down, so every failure is swallowed and the
endpoint always returns 200. No cookies, no third parties — the visitor id is a
random string the browser stores itself.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.db.session import SyncSessionLocal
from app.db.models.page_view import PageView

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Tracking"])


class TrackIn(BaseModel):
    path: str = Field(default="/", max_length=300)
    referrer: str = Field(default="", max_length=300)
    visitor_id: str = Field(default="", max_length=64)


@router.post("/track")
def track(body: TrackIn, request: Request):
    """Record one page view. Always returns ok, never raises."""
    try:
        path = (body.path or "/")[:300]
        # ignore obvious noise so the dashboard stays meaningful
        if path.startswith("/api/") or path in ("/favicon.ico", "/robots.txt"):
            return {"ok": True}
        country = (request.headers.get("cf-ipcountry")
                   or request.headers.get("x-vercel-ip-country") or "")[:80]
        with SyncSessionLocal() as db:
            db.add(PageView(
                path=path,
                referrer=(body.referrer or "")[:300],
                visitor_id=(body.visitor_id or "")[:64],
                country=country,
            ))
            db.commit()
    except Exception:                                   # noqa: BLE001
        logger.debug("page view not recorded", exc_info=True)
    return {"ok": True}
