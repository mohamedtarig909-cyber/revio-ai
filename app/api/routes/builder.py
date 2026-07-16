"""
System Builder — the free-preview funnel.

Generates a genuinely tailored revival-system spec from a plain-language
description: industry-grounded benchmarks, a transparent recoverable-revenue
model (formula shown, conservative), a concrete setup guide, operator notes,
and KPI targets. LLM-enhanced when a funded key exists; deterministic
industry engine otherwise. Rate-limited per IP.
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
# Industry knowledge base (deterministic engine — grounded, conservative)
# Fields: label, half(decay half-life days), deal(avg $), hook, channel,
#         crms(where their leads live), window(best contact time),
#         note(niche-specific operator note), season(timing angle)
# ---------------------------------------------------------------------------
IND = {
    "hvac":        dict(label="HVAC", half=75, deal=6500, hook="seasonal tune-up urgency",
                        channel="sms+email", crms="ServiceTitan, Jobber, Housecall Pro",
                        window="weekdays 8–10am or 4–6pm (homeowners around the house)",
                        note="Quotes die fastest in shoulder seasons — revive before the first heat wave or cold snap, when urgency returns on its own.",
                        season="pre-summer AC / pre-winter furnace checkup"),
    "plumb":       dict(label="Plumbing", half=60, deal=1800, hook="preventive-issue check-in",
                        channel="sms+email", crms="Jobber, Housecall Pro, ServiceTitan",
                        window="weekdays 8–10am",
                        note="Most dead plumbing leads were urgent once — lead with 'still an issue?' not a pitch. Speed matters more than polish here.",
                        season="pre-winter pipe/water-heater checks"),
    "roof":        dict(label="Roofing", half=120, deal=12000, hook="storm-season inspection",
                        channel="email", crms="AccuLynx, JobNimbus, Jobber",
                        window="weekdays 9–11am",
                        note="Insurance-claim angles revive stalled roofing quotes better than discounts. Reference the original inspection date specifically.",
                        season="post-storm and pre-winter inspection windows"),
    "real estate": dict(label="Real Estate", half=240, deal=9000, hook="market-shift update",
                        channel="sms+email", crms="Follow Up Boss, kvCORE, Lofty",
                        window="evenings 6–8pm and Saturday mornings",
                        note="Buyer leads from 12–18 months ago are gold when rates or inventory shift — lead with the market change, never 'just checking in'.",
                        season="spring listing season and January resolution buyers"),
    "realtor":     dict(label="Real Estate", half=240, deal=9000, hook="market-shift update",
                        channel="sms+email", crms="Follow Up Boss, kvCORE, Lofty",
                        window="evenings 6–8pm and Saturday mornings",
                        note="Buyer leads from 12–18 months ago are gold when rates or inventory shift — lead with the market change, never 'just checking in'.",
                        season="spring listing season and January resolution buyers"),
    "solar":       dict(label="Solar", half=180, deal=21000, hook="incentive-deadline angle",
                        channel="email", crms="HubSpot, Aurora, SubcontractorHub",
                        window="weekday evenings 5–7pm",
                        note="Price objections dominate dead solar leads — revive with updated incentive/financing math, not enthusiasm. Show the new monthly number.",
                        season="before annual incentive/tax-credit deadlines"),
    "dent":        dict(label="Dental", half=150, deal=1200, hook="overdue-recall reactivation",
                        channel="sms", crms="Dentrix, Open Dental, Eaglesoft",
                        window="lunch hours and 3–5pm",
                        note="Patient recall is the highest-ROI list in dentistry — 'you're overdue' outperforms any promotion. Keep SMS under 160 chars.",
                        season="year-end insurance-benefits-expiring push"),
    "law":         dict(label="Law Firm", half=90, deal=5000, hook="case-status check-in",
                        channel="email", crms="Clio, Lawmatics, MyCase",
                        window="weekdays 8–9am",
                        note="Consult no-shows usually mean fear, not disinterest — revive with a low-pressure 'your situation may have changed' note. Mind bar advertising rules.",
                        season="new-year and post-tax-season decision windows"),
    "med spa":     dict(label="Med Spa", half=90, deal=900, hook="new-treatment invite",
                        channel="sms", crms="Boulevard, Mindbody, Vagaro",
                        window="weekdays 11am–1pm",
                        note="Consultation ghosts respond to specific-treatment invites with a date, not generic 'we miss you'. Photos/newness drive replies.",
                        season="pre-summer and pre-holiday appearance events"),
    "kitchen":     dict(label="Kitchen Remodeling", half=180, deal=28000, hook="design-consult revival",
                        channel="email", crms="Buildertrend, JobTread, HubSpot",
                        window="weekday evenings and Saturday 10am–12pm",
                        note="Big-ticket remodels stall on money timing — revive quarterly with one new project photo and a financing option, never pressure.",
                        season="pre-holiday completion deadlines ('done by Thanksgiving')"),
    "auto":        dict(label="Auto Repair", half=60, deal=850, hook="service-due reminder",
                        channel="sms", crms="Shop-Ware, Tekmetric, Shopmonkey",
                        window="weekdays 7–9am",
                        note="Declined-service follow-ups are the money list: 'that brake job you postponed' with a firm price beats any coupon blast.",
                        season="pre-winter and pre-road-trip season checks"),
    "insur":       dict(label="Insurance", half=120, deal=2400, hook="policy-review window",
                        channel="email", crms="AgencyBloc, HawkSoft, Applied Epic",
                        window="weekdays 9–11am",
                        note="Quote-shoppers from 6+ months ago are re-shoppable at renewal — time revival to their likely renewal month. Strict TCPA care on SMS.",
                        season="renewal anniversaries and open-enrollment windows"),
    "mortgage":    dict(label="Mortgage", half=150, deal=8000, hook="rate-change alert",
                        channel="email", crms="Jungo, Total Expert, HubSpot",
                        window="weekdays 10am–12pm",
                        note="Every rate drop resurrects your entire dead pipeline — pre-approvals that expired are the first call list. Compliance: no specific rate promises in writing.",
                        season="any meaningful rate movement"),
    "landscap":    dict(label="Landscaping", half=90, deal=4200, hook="seasonal project window",
                        channel="sms+email", crms="Jobber, Aspire, Service Autopilot",
                        window="weekdays 7–9am",
                        note="Quotes die over winter and revive in spring — a February 'lock your spring slot' message beats April competition.",
                        season="pre-spring booking and fall cleanup"),
    "pest":        dict(label="Pest Control", half=60, deal=600, hook="seasonal treatment reminder",
                        channel="sms", crms="FieldRoutes, PestPac, Jobber",
                        window="weekdays 8–10am",
                        note="One-time-service customers are your recurring-plan goldmine — revive with a seasonal threat ('ant season starts now'), not a discount.",
                        season="pre-summer ants/mosquitoes, fall rodents"),
    "fitness":     dict(label="Fitness Studio", half=60, deal=600, hook="comeback-offer nudge",
                        channel="sms", crms="Mindbody, Glofox, PushPress",
                        window="Sunday evening and Monday morning",
                        note="Lapsed members respond to identity ('athletes like you'), trial ghosts to friction removal ('your first class is still waiting').",
                        season="January, pre-summer, and September resets"),
    "gym":         dict(label="Fitness Studio", half=60, deal=600, hook="comeback-offer nudge",
                        channel="sms", crms="Mindbody, Glofox, PushPress",
                        window="Sunday evening and Monday morning",
                        note="Lapsed members respond to identity ('athletes like you'), trial ghosts to friction removal ('your first class is still waiting').",
                        season="January, pre-summer, and September resets"),
    "chiro":       dict(label="Chiropractor", half=90, deal=800, hook="care-plan check-in",
                        channel="sms", crms="Jane, ChiroTouch, Genesis",
                        window="weekdays 11am–1pm",
                        note="Patients who stopped mid-care-plan are the list — 'your last visit left X unfinished' works; wellness content does not.",
                        season="new-year wellness and post-injury seasons"),
    "clean":       dict(label="Cleaning Services", half=60, deal=350, hook="schedule-reset offer",
                        channel="sms+email", crms="Jobber, ZenMaid, Launch27",
                        window="weekdays 9–11am",
                        note="One-time cleans convert to recurring on the third touch on average — sequence for the recurring plan, not another one-off.",
                        season="spring cleaning and pre-holiday hosting"),
    "ecommerce":   dict(label="E-commerce", half=45, deal=120, hook="back-in-stock / winback offer",
                        channel="email", crms="Klaviyo, Shopify, Omnisend",
                        window="Tue–Thu 10am and 8pm sends",
                        note="Winback economics: a past buyer is far cheaper to reactivate than a new one is to acquire — segment by last-order recency and category.",
                        season="BFCM and category seasonality"),
}
DEFAULT_IND = dict(label="Local Services", half=90, deal=3000, hook="value-led check-in",
                   channel="email", crms="your CRM or a simple spreadsheet export",
                   window="weekday mornings 8–10am",
                   note="Lead with the specific reason they contacted you originally — generic 'checking in' messages are why revival campaigns fail.",
                   season="your busy-season ramp-up")

# Conservative model constants (shown transparently to the visitor).
REVIVABLE_RATE = 0.30   # share of dead leads typically worth re-working
CLOSE_RATE = 0.12       # conservative close rate on revived conversations


def _detect_industry(text: str) -> dict:
    t = text.lower()
    for key, ind in IND.items():
        if key in t:
            return ind
    return DEFAULT_IND


def _detect_goal(text: str) -> str:
    m = re.search(r"goal:\s*([^)]+)\)", text)
    return m.group(1).strip() if m else "Revive Dead Leads"


def _detect_lead_count(text: str) -> int:
    nums = [int(m.group(1).replace(",", ""))
            for m in re.finditer(r"(?<![$\d.])(\d[\d,]{1,6})(?!\s*%)", text)
            if not re.search(r"\$\s*$", text[:m.start()])]
    plausible = [n for n in nums if 50 <= n <= 500000]
    return max(plausible) if plausible else 1500


def _template_spec(description: str) -> dict:
    ind = _detect_industry(description)
    goal = _detect_goal(description)
    leads = _detect_lead_count(description)
    deal = ind["deal"]
    revivable = int(leads * REVIVABLE_RATE)
    expected_wins = max(1, int(revivable * CLOSE_RATE))
    recoverable = int(revivable * CLOSE_RATE * deal)
    ch = ind["channel"]
    return {
        "generated_by": "template_engine",
        "business_profile": {
            "industry": ind["label"], "estimated_dead_leads": leads,
            "est_avg_deal_value": deal, "primary_channel": ch,
            "positioning_hook": ind["hook"], "goal": goal,
            "leads_live_in": ind["crms"],
        },
        "scoring_config": {
            "model": "Dead Lead Score v2 (deterministic)",
            "decay_halflife_days": ind["half"],
            "factors": ["intent", "engagement_history", "objection_type",
                        "time_decay", "sentiment", "conversion_probability"],
            "objection_multipliers": {"no_followup": 1.0, "bad_timing": 0.8,
                                      "price": 0.55, "competitor": 0.3, "unqualified": 0.2},
        },
        "the_math": {
            "headline": recoverable,
            "formula": f"{leads:,} dead leads × {int(REVIVABLE_RATE*100)}% typically revivable × {int(CLOSE_RATE*100)}% conservative close rate × ${deal:,} avg deal",
            "revivable_leads": revivable,
            "expected_wins": expected_wins,
            "disclaimer": "Deliberately conservative planning model — not a promise. Your real numbers come from scoring your actual list.",
        },
        "revival_sequence": [
            {"step": 1, "day": 0,  "channel": "email", "angle": "Honest re-open — reference their original inquiry, by name and date"},
            {"step": 2, "day": 3,  "channel": ch.split("+")[0], "angle": f"Value nudge — {ind['hook']}"},
            {"step": 3, "day": 7,  "channel": "email", "angle": "Objection-specific answer (auto-matched to why they went cold)"},
            {"step": 4, "day": 14, "channel": ch.split("+")[-1], "angle": "Easy next step — one-click booking, zero pressure"},
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
        "setup_guide": [
            f"Export your dead/lost leads from {ind['crms'].split(',')[0]} (or any CSV): name, email, phone, last-contact date, deal value, lost reason.",
            "Upload the CSV — Revio scores every lead 0–100 and diagnoses why each went cold.",
            "Review the ranked list: work only the top-scored leads (that's where the money concentrates).",
            f"Approve the drafted sequence — sends go out in the {ind['label'].lower()} sweet spot: {ind['window']}.",
            "Route replies to a human within 5 minutes — speed-to-reply is where revived deals are won or lost.",
            "Check the recovered-revenue ledger weekly; kill angles that don't reply, double down on ones that do.",
        ],
        "operator_notes": [
            ind["note"],
            f"Timing angle for this niche: {ind['season']}.",
            f"Best contact window: {ind['window']}.",
            "Never fake familiarity or urgency — revival works because it's honest about the dropped ball.",
            "Opt-outs are suppressed instantly and permanently; every send needs your approval by default.",
        ],
        "kpis": [
            {"metric": "Reply rate on revival sequence", "target": "3–8%", "why": "Below 3% = wrong angle or stale list; rewrite step 1, don't push volume."},
            {"metric": "Speed-to-reply (human response)", "target": "under 5 min", "why": "Contact rates collapse as response time grows — this single habit moves revenue most."},
            {"metric": "Booked conversations / 100 revived", "target": "2–5", "why": "The honest conversion midpoint for dead-list campaigns; scale list size from here."},
            {"metric": "Recovered revenue vs. cost", "target": "10×+ by month 2", "why": f"At ~${deal:,} avg deal, {expected_wins} win(s) already clears it — track in the ledger, not vibes."},
        ],
        "sell_kit": {
            "suggested_retainer": "$500–$1,500/mo per client",
            "pitch_opener": (f"You're sitting on ~{leads:,} leads you already paid for. "
                             f"Industry-typical: about {int(REVIVABLE_RATE*100)}% are still winnable. "
                             "I run an AI system that finds them, shows why they went cold, and drafts the revival — you approve every send."),
            "includes": ["cold-call script", "ROI one-pager", "onboarding checklist",
                         "client report template"],
        },
        "locked_components": [
            "Full 5-message copy in the client's voice",
            "Live scoring on their real CSV",
            "Why-it-died diagnosis per lead",
            "Best-window send timing automation",
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
        "You configure AI lead-revival systems for local businesses. Be concrete, honest, "
        "conservative — no hype, no invented statistics. Given this client description, return ONLY JSON "
        "with keys: business_profile{industry, estimated_dead_leads:int, est_avg_deal_value:int, "
        "primary_channel, positioning_hook, goal, leads_live_in}, revival_sequence (5 steps: step,day,"
        "channel,angle — tailored to this niche), sample_message (short honest re-engagement email with "
        "{first_name}, niche-specific), projected_recoverable_usd:int (conservative), setup_guide (6 "
        "numbered concrete steps naming this niche's actual tools), operator_notes (5 tactical notes "
        "specific to this niche and goal), kpis (4 of {metric,target,why} with honest ranges), "
        "sell_kit{suggested_retainer, pitch_opener}. Description: " + description
    )
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                settings.openai_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={"model": settings.llm_model_small, "max_tokens": 1400, "temperature": 0.4,
                      "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": prompt}]},
            )
        if r.status_code != 200:
            return None
        data = json.loads(r.json()["choices"][0]["message"]["content"])
        for k in ("business_profile", "revival_sequence", "sample_message",
                  "projected_recoverable_usd", "setup_guide", "operator_notes",
                  "kpis", "sell_kit"):
            if k in data:
                base[k] = data[k]
        if isinstance(base.get("projected_recoverable_usd"), int):
            base["the_math"]["headline"] = base["projected_recoverable_usd"]
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
    """Generate a tailored revival-system spec from a plain-language description."""
    ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() \
        or (request.client.host if request.client else "unknown")
    if not _rate_ok(ip):
        raise HTTPException(status_code=429, detail="Builder limit reached — try again in an hour")
    if body.email:
        logger.info("[builder-lead] email=%s desc=%s", body.email, body.description[:120])
    spec = await _llm_spec(body.description) or _template_spec(body.description)
    return spec
