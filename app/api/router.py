from fastapi import APIRouter

from app.api.routes import admin, auth, builder, crm, dashboard, leads, operations, systems, upload, webhooks

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(builder.router)
api_router.include_router(systems.router)
api_router.include_router(dashboard.router)
api_router.include_router(leads.router)
api_router.include_router(operations.router)
api_router.include_router(admin.router)
api_router.include_router(crm.router)
api_router.include_router(upload.router)
api_router.include_router(webhooks.stripe_router)
api_router.include_router(webhooks.crm_webhook_router)
api_router.include_router(webhooks.whop_router)
