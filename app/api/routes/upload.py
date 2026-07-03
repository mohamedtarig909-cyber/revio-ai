from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.core.rate_limit import limiter
from app.core.security import get_current_user
from app.db.models.user import User
from app.db.session import SyncSessionLocal
from app.schemas import CSVUploadResponse
from app.services.ingest.csv_service import CSVImportService
from app.workers.tasks.agent_tasks import run_orchestrator_pipeline_task

router = APIRouter(prefix="/upload", tags=["Upload"])


@router.post("/csv", response_model=CSVUploadResponse)
@limiter.limit("10/minute")
async def upload_csv(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
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
        try:
            # Queue the AI pipeline if a broker (Redis/Celery) is available.
            run_orchestrator_pipeline_task.delay(str(current_user.organization_id))
        except Exception:  # noqa: BLE001 — no broker: import still succeeds
            pass  # agents can be triggered manually from /admin
        return CSVUploadResponse(**result)
    finally:
        db.close()
