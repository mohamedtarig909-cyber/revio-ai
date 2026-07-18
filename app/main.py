import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

WEB_DIR = Path(__file__).parent / "web"

from app import __version__
from app.api.router import api_router
from app.config import get_settings
from app.core.rate_limit import limiter
from app.core.sentry import init_sentry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
settings = get_settings()
init_sentry()

app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Autonomous revenue intelligence operating system",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", include_in_schema=False)
async def homepage():
    """Serve the Revio AI marketing site (one deploy = site + API)."""
    return FileResponse(WEB_DIR / "index.html")


@app.get("/download", include_in_schema=False)
async def download_site():
    return FileResponse(WEB_DIR / "index.html", media_type="text/html",
                        filename="revio-ai-website.html")


@app.get("/admin", include_in_schema=False)
async def admin_panel():
    """Operator control panel — drive & test the system (uses ADMIN_TOKEN)."""
    return FileResponse(WEB_DIR / "admin.html")


@app.get("/compare", include_in_schema=False)
async def compare_page():
    """Honest comparison page vs alternatives (AEO / SEO)."""
    return FileResponse(WEB_DIR / "compare.html")


@app.get("/llms.txt", include_in_schema=False)
async def llms_txt():
    return FileResponse(WEB_DIR / "llms.txt", media_type="text/plain")


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return FileResponse(WEB_DIR / "robots.txt", media_type="text/plain")


@app.get("/database-reactivation", include_in_schema=False)
async def guide_page():
    """SEO pillar page: database reactivation guide."""
    return FileResponse(WEB_DIR / "guide.html")


from app.api.routes.seo_pages import router as seo_router  # noqa: E402
app.include_router(seo_router)


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    from fastapi.responses import Response
    from app.api.routes.seo_pages import SLUGS
    base = "https://revioai.site"
    urls = [
        (f"{base}/", "1.0", "weekly"),
        (f"{base}/compare", "0.8", "monthly"),
        (f"{base}/database-reactivation", "0.9", "monthly"),
    ]
    urls += [(f"{base}/revive/{slug}", "0.8", "monthly") for slug in SLUGS]
    body = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for loc, pr, cf in urls:
        body += f"  <url><loc>{loc}</loc><changefreq>{cf}</changefreq><priority>{pr}</priority></url>\n"
    body += "</urlset>\n"
    return Response(content=body, media_type="application/xml")


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": __version__, "service": "revio-ai-api"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
