import logging
from urllib.parse import urlencode
from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.encryption import token_encryption
from app.db.models.crm_integration import CRMIntegration, CRMProvider, SyncStatus

logger = logging.getLogger(__name__)
settings = get_settings()


class HubSpotOAuthService:
    AUTH_URL = "https://app.hubspot.com/oauth/authorize"
    TOKEN_URL = "https://api.hubapi.com/oauth/v1/token"

    def get_authorization_url(self, organization_id: UUID) -> str:
        params = urlencode(
            {
                "client_id": settings.hubspot_client_id,
                "redirect_uri": settings.hubspot_redirect_uri,
                "scope": "crm.objects.contacts.read crm.objects.deals.read oauth",
                "state": str(organization_id),
            }
        )
        return f"{self.AUTH_URL}?{params}"

    async def handle_callback(self, db: Session, code: str, organization_id: UUID) -> CRMIntegration:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.hubspot_client_id,
                    "client_secret": settings.hubspot_client_secret,
                    "redirect_uri": settings.hubspot_redirect_uri,
                    "code": code,
                },
            )
            response.raise_for_status()
            tokens = response.json()

        integration = CRMIntegration(
            organization_id=organization_id,
            provider=CRMProvider.HUBSPOT,
            access_token_encrypted=token_encryption.encrypt(tokens["access_token"]),
            refresh_token_encrypted=token_encryption.encrypt(tokens.get("refresh_token", "")),
            sync_status=SyncStatus.IDLE,
        )
        db.add(integration)
        db.commit()
        db.refresh(integration)

        from app.workers.tasks.agent_tasks import run_orchestrator_pipeline_task

        run_orchestrator_pipeline_task.delay(str(organization_id))
        return integration


class SalesforceOAuthService:
    AUTH_URL = "https://login.salesforce.com/services/oauth2/authorize"
    TOKEN_URL = "https://login.salesforce.com/services/oauth2/token"

    def get_authorization_url(self, organization_id: UUID) -> str:
        params = urlencode(
            {
                "response_type": "code",
                "client_id": settings.salesforce_client_id,
                "redirect_uri": settings.salesforce_redirect_uri,
                "state": str(organization_id),
            }
        )
        return f"{self.AUTH_URL}?{params}"

    async def handle_callback(self, db: Session, code: str, organization_id: UUID) -> CRMIntegration:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.salesforce_client_id,
                    "client_secret": settings.salesforce_client_secret,
                    "redirect_uri": settings.salesforce_redirect_uri,
                    "code": code,
                },
            )
            response.raise_for_status()
            tokens = response.json()

        integration = CRMIntegration(
            organization_id=organization_id,
            provider=CRMProvider.SALESFORCE,
            access_token_encrypted=token_encryption.encrypt(tokens["access_token"]),
            refresh_token_encrypted=token_encryption.encrypt(tokens.get("refresh_token", "")),
            instance_url=tokens.get("instance_url"),
            sync_status=SyncStatus.IDLE,
        )
        db.add(integration)
        db.commit()
        db.refresh(integration)

        from app.workers.tasks.agent_tasks import run_orchestrator_pipeline_task

        run_orchestrator_pipeline_task.delay(str(organization_id))
        return integration
