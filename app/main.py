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


@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": __version__, "service": "revio-ai-api"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.getLogger(__name__).exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
