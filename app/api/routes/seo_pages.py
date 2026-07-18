"""
Programmatic SEO pages: one landing page per industry, generated from the
builder's knowledge base. Each page targets long-tail searches like
"revive dead HVAC leads" with unique, niche-specific content and FAQ schema.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response

from app.api.routes.builder import CLOSE_RATE, IND, REVIVABLE_RATE

router = APIRouter()

# slug -> IND key
SLUGS = {
    "hvac-leads": "hvac",
    "plumbing-leads": "plumb",
    "roofing-leads": "roof",
    "real-estate-leads": "real estate",
    "solar-leads": "solar",
    "dental-leads": "dent",
    "law-firm-leads": "law",
    "med-spa-leads": "med spa",
    "kitchen-remodeling-leads": "kitchen",
    "auto-repair-leads": "auto",
    "insurance-leads": "insur",
    "mortgage-leads": "mortgage",
    "landscaping-leads": "landscap",
    "pest-control-leads": "pest",
    "fitness-leads": "fitness",
    "chiropractic-leads": "chiro",
    "cleaning-leads": "clean",
    "ecommerce-customers": "ecommerce",
}

_CSS = """
:root{--bg:#09090b;--card:#141417;--bd:rgba(255,255,255,.1);--tx:#fff;--mut:rgba(255,255,255,.62);--dim:rgba(255,255,255,.42);--sig:#2DD4BF}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Poppins,system-ui,sans-serif;background:var(--bg);color:var(--tx);line-height:1.7;padding:40px 20px;max-width:760px;margin:0 auto}
h1{font-weight:600;font-size:clamp(28px,5vw,40px);letter-spacing:-1px;line-height:1.1;margin-bottom:16px}
h2{font-weight:600;font-size:22px;margin:40px 0 12px;letter-spacing:-.4px}
p,li{color:var(--mut);margin-bottom:13px}
ol,ul{padding-left:22px;margin-bottom:16px}
b,strong{color:var(--tx)}
a{color:var(--sig)}
.def{color:var(--tx);font-size:16.5px;background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:18px 20px;margin:18px 0}
.box{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:18px 20px;margin:16px 0}
.cta{display:inline-block;background:#fff;color:#0a0a0b;font-weight:600;padding:14px 26px;border-radius:999px;text-decoration:none;margin:18px 0}
.small{font-size:12.5px;color:var(--dim)}
.back{display:inline-block;margin-bottom:24px;color:var(--mut);text-decoration:none}
"""


def _page(slug: str, key: str) -> str:
    d = IND[key]
    label = d["label"]
    leads = 1500
    revivable = int(leads * REVIVABLE_RATE)
    wins = max(1, int(revivable * CLOSE_RATE))
    recover = int(revivable * CLOSE_RATE * d["deal"])
    title = f"Revive Dead {label} Leads with AI | Revio AI"
    desc = (f"How {label.lower()} businesses reactivate old leads: why they go cold, "
            f"the best re-contact windows, and how AI scores and revives them. "
            f"Typical lists hold ${recover:,}+ in recoverable revenue.")
    url = f"https://revioai.site/revive/{slug}"
    faq = [
        (f"How many dead {label.lower()} leads can be revived?",
         f"Around {int(REVIVABLE_RATE*100)}% of a typical {label.lower()} dead-lead list is still worth re-working, "
         f"because most leads went quiet from missed follow-up or bad timing rather than a real no. "
         f"Scoring the list first concentrates effort on the winnable share."),
        (f"When is the best time to re-contact {label.lower()} leads?",
         f"For {label.lower()}, the reliable contact window is {d['window']}. Seasonally: {d['season']}."),
        (f"Where do {label.lower()} businesses keep their dead leads?",
         f"Usually inside {d['crms']}, or in an old spreadsheet export. Any CSV with a name, "
         "contact, last-contact date and deal value is enough to score the list."),
    ]
    faq_ld = ",".join(
        '{"@type":"Question","name":"%s","acceptedAnswer":{"@type":"Answer","text":"%s"}}'
        % (q.replace('"', "'"), a.replace('"', "'")) for q, a in faq
    )
    faq_html = "".join(f"<h2>{q}</h2><p>{a}</p>" for q, a in faq)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"/><meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>{title}</title>
<meta name="description" content="{desc}"/>
<link rel="canonical" href="{url}"/>
<meta property="og:title" content="{title}"/><meta property="og:description" content="{desc}"/><meta property="og:url" content="{url}"/>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='8' fill='%232DD4BF'/><path d='M5 18h4l3 6 4-16 3 10h8' fill='none' stroke='%2306080D' stroke-width='2.6' stroke-linecap='round' stroke-linejoin='round'/></svg>"/>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600&display=swap" rel="stylesheet"/>
<script type="application/ld+json">{{"@context":"https://schema.org","@graph":[
 {{"@type":"Article","headline":"{title}","url":"{url}","publisher":{{"@type":"Organization","name":"Revio AI","url":"https://revioai.site/"}}}},
 {{"@type":"FAQPage","mainEntity":[{faq_ld}]}}]}}</script>
<style>{_CSS}</style>
</head><body>
<a class="back" href="/">&larr; Revio AI home</a>
<h1>Revive Dead {label} Leads with AI</h1>
<div class="def"><b>Most "dead" {label.lower()} leads are not dead.</b> They went quiet because nobody followed up,
or the timing was wrong. Revio AI scores every old lead 0&ndash;100, diagnoses why it went cold,
and drafts the revival campaign. You approve every message before it sends.</div>

<h2>The math on a typical {label.lower()} list</h2>
<div class="box"><p style="margin:0"><b>{leads:,} dead leads</b> &times; {int(REVIVABLE_RATE*100)}% typically revivable
&times; {int(CLOSE_RATE*100)}% conservative close rate &times; <b>${d['deal']:,} average deal</b>
= <b style="color:var(--sig)">${recover:,} recoverable</b> (about {wins} recovered deals).</p>
<p class="small" style="margin:10px 0 0">Deliberately conservative planning model. Your real number comes from scoring your actual list.</p></div>

<h2>What actually revives {label.lower()} leads</h2>
<ul>
<li><b>Field note:</b> {d['note']}</li>
<li><b>Best contact window:</b> {d['window']}.</li>
<li><b>Timing angle:</b> {d['season']}.</li>
<li><b>Where the leads live:</b> {d['crms']}, or any CSV export.</li>
</ul>

<h2>How it works with Revio</h2>
<ol>
<li>Export your dead and lost leads from {d['crms'].split(',')[0]} (or any CSV).</li>
<li>Upload the list. Every lead gets a 0&ndash;100 score and a cause-of-death diagnosis.</li>
<li>Work only the top-scored leads. That is where the money concentrates.</li>
<li>Approve the drafted {d['channel'].replace('+', ' and ')} sequence. Nothing sends without your OK.</li>
<li>Track recovered revenue in the ledger, weekly.</li>
</ol>
<a class="cta" href="/#builder">Build your {label.lower()} revival system free &rarr;</a>

{faq_html}

<h2>Learn more</h2>
<p><a href="/database-reactivation">The complete database reactivation guide</a> &middot;
<a href="/compare">Revio AI vs the alternatives</a> &middot; <a href="/">Try the builder</a></p>
<p class="small">&copy; Revio AI &middot; <a href="/">revioai.site</a></p>
</body></html>"""


@router.get("/revive/{slug}", include_in_schema=False)
async def revive_page(slug: str):
    key = SLUGS.get(slug)
    if not key:
        return Response(status_code=404)
    return HTMLResponse(_page(slug, key))
