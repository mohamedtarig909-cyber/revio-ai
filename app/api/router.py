from fastapi import APIRouter

from app.api.routes import admin, crm, dashboard, leads, operations, upload, webhooks

api_router = APIRouter()
api_router.include_router(dashboard.router)
api_router.include_router(leads.router)
api_router.include_router(operations.router)
api_router.include_router(admin.router)
api_router.include_router(crm.router)
api_router.include_router(upload.router)
api_router.include_router(webhooks.stripe_router)
api_router.include_router(webhooks.crm_webhook_router)
