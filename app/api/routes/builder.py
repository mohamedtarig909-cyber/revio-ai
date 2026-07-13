"""
System Builder — the free-preview funnel.

A visitor describes a client business in plain language; we generate their
complete revival-system spec (profile, scoring config, sequence, sample
message, sell kit). The site renders it being "assembled" — full access
requires a subscription.

Cost-safe: tries a cheap LLM call (gpt-4o-mini) when a key+credit exist,
otherwise falls back to a deterministic industry template engine so the
funnel works with zero AI spend. Rate-limited per IP.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/builder", tags=["System Builder"])


class BuildIn(BaseModel):
    description: str = Field(..., min_length=10, max_length=600)
    email: str = ""          # optional — captured for follow-up


# ---------------------------------------------------------------------------
# Industry template library (deterministic fallback — no AI cost)
# ---------------------------------------------------------------------------
INDUSTRIES = {
    "hvac":        {"label": "HVAC", "decay_halflife_days": 75,  "avg_deal": 6500,
                    "hook": "seasonal tune-up urgency", "channel": "sms+email"},
    "plumb":       {"label": "Plumbing", "decay_halflife_days": 60, "avg_deal": 1800,
                    "hook": "preventive-issue check-in", "channel": "sms+email"},
    "roof":        {"label": "Roofing", "decay_halflife_days": 120, "avg_deal": 12000,
                    "hook": "storm-season inspection", "channel": "email"},
    "real estate": {"label": "Real Estate", "decay_halflife_days": 240, "avg_deal": 9000,
                    "hook": "market-shift update", "channel": "sms+email"},
    "realtor":     {"label": "Real Estate", "decay_halflife_days": 240, "avg_deal": 9000,
                    "hook": "market-shift update", "channel": "sms+email"},
    "solar":       {"label": "Solar", "decay_halflife_days": 180, "avg_deal": 21000,
                    "hook": "incentive-deadline angle", "channel": "email"},
    "dent":        {"label": "Dental", "decay_halflife_days": 150, "avg_deal": 1200,
                    "hook": "overdue-recall reactivation", "channel": "sms"},
    "med spa":     {"label": "Med Spa", "decay_halflife_days": 90, "avg_deal": 900,
                    "hook": "new-treatment invite", "channel": "sms"},
    "insur":       {"label": "Insurance", "decay_halflife_days": 120, "avg_deal": 2400,
                    "hook": "policy-review window", "channel": "email"},
    "mortgage":    {"label": "Mortgage", "decay_halflife_days": 150, "avg_deal": 8000,
                    "hook": "rate-change alert", "channel": "email"},
    "gym":         {"label": "Fitness", "decay_halflife_days": 60, "avg_deal": 600,
                    "hook": "comeback-offer nudge", "channel": "sms"},
}
DEFAULT_IND = {"label": "Local Services", "decay_halflife_days": 90, "avg_deal": 3000,
               "hook": "value-led check-in", "channel": "email"}


def _detect_industry(text: str) -> dict:
    t = text.lower()
    for key, ind in INDUSTRIES.items():
        if key in t:
            return ind
    return DEFAULT_IND


def _detect_lead_count(text: str) -> int:
    # Ignore dollar amounts ($6,500) — only bare numbers count as lead counts.
    nums = [int(m.group(1).replace(",", ""))
            for m in re.finditer(r"(?<![$\d.])(\d[\d,]{1,6})(?!\s*%)", text)
            if not re.search(r"\$\s*$", text[:m.start()])]
    plausible = [n for n in nums if 50 <= n <= 500000]
    return max(plausible) if plausible else 1500


def _template_spec(description: str) -> dict:
    ind = _detect_industry(description)
    leads = _detect_lead_count(description)
    deal = ind["avg_deal"]
    recoverable = int(leads * 0.30 * 0.12 * deal)   # conservative: 30% revivable, 12% close
    return {
        "generated_by": "template_engine",
        "business_profile": {
            "industry": ind["label"], "estimated_dead_leads": leads,
            "est_avg_deal_value": deal,
            "primary_channel": ind["channel"],
            "positioning_hook": ind["hook"],
        },
        "scoring_config": {
            "model": "Dead Lead Score v2 (deterministic)",
            "decay_halflife_days": ind["decay_halflife_days"],
            "factors": ["intent", "engagement_history", "objection_type",
                        "time_decay", "sentiment", "conversion_probability"],
            "objection_multipliers": {"no_followup": 1.0, "bad_timing": 0.8,
                                      "price": 0.55, "competitor": 0.3, "unqualified": 0.2},
        },
        "revival_sequence": [
            {"step": 1, "day": 0,  "channel": "email", "angle": "Honest re-open — reference their original inquiry"},
            {"step": 2, "day": 3,  "channel": ind["channel"].split("+")[0], "angle": f"Value nudge — {ind['hook']}"},
            {"step": 3, "day": 7,  "channel": "email", "angle": "Objection-specific answer (auto-matched to why they went cold)"},
            {"step": 4, "day": 14, "channel": ind["channel"].split("+")[-1], "angle": "Social proof + easy next step (book a call)"},
            {"step": 5, "day": 21, "channel": "email", "angle": "Polite breakup — leaves the door open, cleans the list"},
        ],
        "sample_message": (
            f"Subject: Still thinking about your {ind['label'].lower()} project?\n\n"
            "Hi {first_name} — you reached out to us a while back and things went "
            "quiet on our end; that's on us. If the timing's better now, I'd be glad "
            "to pick up where we left off — no pressure either way. Want me to send "
            "over the updated details?"
        ),
        "projected_recoverable_usd": recoverable,
        "sell_kit": {
            "suggested_retainer": "$500–$1,500/mo per client",
            "pitch_opener": (f"You're sitting on ~{leads:,} leads you already paid for. "
                             "I revive them with an AI system — you only pay when it's running."),
            "includes": ["cold-call script", "ROI one-pager", "onboarding checklist",
                         "client report template"],
        },
        "locked_components": [
            "Full 5-message copy in the client's voice",
            "Automated scoring on their real CSV",
            "Why-it-died diagnosis per lead",
            "Best-window send timing",
            "Client dashboard + daily report",
            "Sell kit downloads",
        ],
    }


async def _llm_spec(description: str) -> dict | None:
    """Upgrade path: one cheap JSON-mode call when a funded key exists."""
    if not settings.openai_api_key:
        return None
    base = _template_spec(description)
    prompt = (
        "You configure AI lead-revival systems. Given this client description, "
        "return ONLY JSON with keys: business_profile{industry, estimated_dead_leads:int, "
        "est_avg_deal_value:int, primary_channel, positioning_hook}, revival_sequence "
        "(5 steps: step,day,channel,angle), sample_message (short, honest, human re-engagement "
        "email with {first_name}), projected_recoverable_usd:int (conservative), "
        "sell_kit{suggested_retainer, pitch_opener}. Description: " + description
    )
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r = await client.post(
                settings.openai_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.llm_model_small, "max_tokens": 900, "temperature": 0.4,
                      "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}]},
            )
        if r.status_code != 200:
            return None
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        base.update({k: v for k, v in data.items() if k in
                     ("business_profile", "revival_sequence", "sample_message",
                      "projected_recoverable_usd", "sell_kit")})
        base["generated_by"] = "ai"
        return base
    except Exception as e:  # noqa: BLE001
        logger.warning("builder LLM fallback: %s", e)
        return None


# Manual per-IP rate limit (slowapi's decorator breaks Pydantic body parsing).
_hits: dict[str, list[float]] = defaultdict(list)
_WINDOW, _MAX = 3600.0, 6


def _rate_ok(ip: str) -> bool:
    now = time.time()
    _hits[ip] = [t for t in _hits[ip] if now - t < _WINDOW]
    if len(_hits[ip]) >= _MAX:
        return False
    _hits[ip].append(now)
    return True


@router.post("/preview")
async def build_preview(request: Request, body: BuildIn):
    """Generate a client revival-system spec from a plain-language description."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "unknown")
    if not _rate_ok(ip):
        raise HTTPException(status_code=429, detail="Builder limit reached — try again in an hour")
    if body.email:
        logger.info("[builder-lead] email=%s desc=%s", body.email, body.description[:120])
    spec = await _llm_spec(body.description) or _template_spec(body.description)
    return spec
