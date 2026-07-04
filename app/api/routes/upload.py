import logging
import threading

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.rate_limit import limiter
from app.core.security import get_paid_user
from app.db.models.user import User
from app.db.session import SyncSessionLocal
from app.schemas import CSVUploadResponse
from app.services.ingest.csv_service import CSVImportService
from app.workers.tasks.agent_tasks import run_orchestrator_pipeline_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/upload", tags=["Upload"])


def _run_pipeline_bg(org_id: str) -> None:
    """Run the full agent pipeline in-process (fallback when no Celery broker)."""
    from app.orchestrator.engine import OrchestratorEngine
    db = SyncSessionLocal()
    try:
        OrchestratorEngine(db).run_full_pipeline(org_id)
    except Exception:  # noqa: BLE001
        logger.exception("In-process pipeline failed for org %s", org_id)
    finally:
        db.close()


def _kick_pipeline(org_id: str) -> str:
    """Queue on Celery if available, else run in a background thread."""
    try:
        run_orchestrator_pipeline_task.delay(org_id)
        return "queued"
    except Exception:  # noqa: BLE001 — no broker: run inline in a thread
        threading.Thread(target=_run_pipeline_bg, args=(org_id,), daemon=True).start()
        return "running_in_background"


@router.post("/csv", response_model=CSVUploadResponse)
@limiter.limit("10/minute")
async def upload_csv(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_paid_user),
):
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")

    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    db = SyncSessionLocal()
    try:
        result = CSVImportService(db).import_csv(current_user.organization_id, content)
        _kick_pipeline(str(current_user.organization_id))
        return CSVUploadResponse(**result)
    finally:
        db.close()


@router.post("/run-pipeline")
async def run_pipeline_now(current_user: User = Depends(get_paid_user)):
    """Customer-facing: run the full AI agent pipeline on your workspace now."""
    if not current_user.organization_id:
        raise HTTPException(status_code=400, detail="No organization")
    mode = _kick_pipeline(str(current_user.organization_id))
    return {"started": True, "mode": mode}
