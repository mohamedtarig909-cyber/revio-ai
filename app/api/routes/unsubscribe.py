"""One-click unsubscribe.

Linked from the footer of every outbound message. Deliberately simple: no login,
no confirmation step, no "are you sure" — a recipient asking to be left alone
should be honored on the first click, which is both the law and good manners.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.db.session import SyncSessionLocal
from app.services.compliance import suppress, verify_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Unsubscribe"])

_PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<meta name="robots" content="noindex,nofollow"/><title>{title}</title>
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0B0F0E;
color:#E9F2EE;font-family:Poppins,system-ui,sans-serif;padding:24px;line-height:1.6}}
.card{{max-width:440px;background:#131D1A;border:1px solid rgba(255,255,255,.09);
border-radius:18px;padding:34px 30px;text-align:center}}
.ico{{width:52px;height:52px;border-radius:14px;margin:0 auto 18px;display:grid;
place-items:center;font-size:25px;background:{icobg}}}
h1{{font-size:20px;font-weight:600;margin:0 0 10px}}
p{{color:rgba(233,242,238,.62);font-size:14.5px;margin:0}}
.sm{{color:rgba(233,242,238,.4);font-size:12.5px;margin-top:18px}}
</style></head><body><div class="card">
<div class="ico">{ico}</div><h1>{heading}</h1><p>{body}</p>
<p class="sm">Revio AI</p></div></body></html>"""


def _page(title, ico, icobg, heading, body, status=200):
    return HTMLResponse(_PAGE.format(title=title, ico=ico, icobg=icobg,
                                     heading=heading, body=body), status_code=status)


@router.get("/unsubscribe", include_in_schema=False)
def unsubscribe(o: str = Query("", description="organization id"),
                c: str = Query("email", description="channel"),
                v: str = Query("", description="address or number"),
                t: str = Query("", description="signature")):
    if not (o and v and t) or not verify_token(o, c, v, t):
        return _page("Link not valid", "!", "rgba(251,113,133,.15)",
                     "This link is not valid",
                     "The unsubscribe link looks incomplete or altered. "
                     "Please reply to the message with the word STOP and we "
                     "will remove you right away.", status=400)
    try:
        org_id = UUID(o)
    except ValueError:
        return _page("Link not valid", "!", "rgba(251,113,133,.15)",
                     "This link is not valid",
                     "Reply with STOP to any message and we will remove you.", status=400)

    try:
        with SyncSessionLocal() as db:
            suppress(db, org_id, c if c in ("email", "sms") else "email", v,
                     reason="unsubscribed", source="unsubscribe_link")
    except Exception:                                   # noqa: BLE001
        logger.exception("unsubscribe failed for %s", v)
        return _page("Something went wrong", "!", "rgba(251,113,133,.15)",
                     "We could not process that",
                     "Please reply to the message with STOP and a human will "
                     "remove you within one business day.", status=500)

    return _page("You are unsubscribed", "✓", "rgba(45,212,191,.15)",
                 "You are unsubscribed",
                 "You will not receive any further messages from this sender. "
                 "This takes effect immediately and is permanent.")
