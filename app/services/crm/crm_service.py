import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.encryption import token_encryption
from app.db.models.crm_integration import CRMIntegration, CRMProvider, SyncStatus
from app.db.models.lead import Lead, LeadStatus

logger = logging.getLogger(__name__)
settings = get_settings()


class HubSpotCRMService:
    BASE_URL = "https://api.hubapi.com"

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token
        self.headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    async def refresh_token(self, refresh_token: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://api.hubapi.com/oauth/v1/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": settings.hubspot_client_id,
                    "client_secret": settings.hubspot_client_secret,
                    "refresh_token": refresh_token,
                },
            )
            response.raise_for_status()
            return response.json()

    async def fetch_contacts_with_deals(self, limit: int = 100) -> list[dict]:
        contacts: list[dict] = []
        after: str | None = None

        async with httpx.AsyncClient(timeout=60) as client:
            while True:
                params: dict = {"limit": min(limit, 100), "properties": "firstname,lastname,email,phone,notes_last_contacted,hs_lead_status,company"}
                if after:
                    params["after"] = after

                response = await client.get(
                    f"{self.BASE_URL}/crm/v3/objects/contacts",
                    headers=self.headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()

                for contact in data.get("results", []):
                    props = contact.get("properties", {})
                    deal_value, stage = await self._get_primary_deal(client, contact["id"])
                    contacts.append(
                        {
                            "crm_lead_id": contact["id"],
                            "full_name": f"{props.get('firstname', '')} {props.get('lastname', '')}".strip(),
                            "email": props.get("email"),
                            "phone": props.get("phone"),
                            "company": props.get("company"),
                            "last_contact_date": props.get("notes_last_contacted"),
                            "pipeline_stage": stage,
                            "deal_value": deal_value,
                            "notes": "",
                        }
                    )

                paging = data.get("paging", {}).get("next", {})
                after = paging.get("after")
                if not after or len(contacts) >= limit:
                    break

        return contacts

    async def _get_primary_deal(self, client: httpx.AsyncClient, contact_id: str) -> tuple[Decimal | None, str | None]:
        response = await client.get(
            f"{self.BASE_URL}/crm/v3/objects/contacts/{contact_id}/associations/deals",
            headers=self.headers,
        )
        if response.status_code != 200:
            return None, None

        deal_ids = [r["id"] for r in response.json().get("results", [])]
        if not deal_ids:
            return None, None

        deal_response = await client.get(
            f"{self.BASE_URL}/crm/v3/objects/deals/{deal_ids[0]}",
            headers=self.headers,
            params={"properties": "amount,dealstage"},
        )
        if deal_response.status_code != 200:
            return None, None

        props = deal_response.json().get("properties", {})
        amount = props.get("amount")
        return (Decimal(amount) if amount else None, props.get("dealstage"))


class SalesforceCRMService:
    def __init__(self, access_token: str, instance_url: str) -> None:
        self.access_token = access_token
        self.instance_url = instance_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}

    async def fetch_leads(self, limit: int = 200) -> list[dict]:
        query = (
            "SELECT Id, Name, Email, Phone, Company, Status, LastActivityDate, "
            "Description FROM Lead LIMIT {limit}"
        ).format(limit=limit)

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                f"{self.instance_url}/services/data/v59.0/query",
                headers=self.headers,
                params={"q": query},
            )
            response.raise_for_status()
            records = response.json().get("records", [])

        return [
            {
                "crm_lead_id": r["Id"],
                "full_name": r.get("Name", ""),
                "email": r.get("Email"),
                "phone": r.get("Phone"),
                "company": r.get("Company"),
                "last_contact_date": r.get("LastActivityDate"),
                "pipeline_stage": r.get("Status"),
                "deal_value": None,
                "notes": r.get("Description"),
            }
            for r in records
        ]


class CRMSyncService:
    def __init__(self, db: Session) -> None:
        self.db = db

    async def sync_organization(self, organization_id: UUID) -> int:
        integration = self._get_integration(organization_id)
        if not integration:
            logger.warning("No CRM integration for org %s", organization_id)
            return 0

        integration.sync_status = SyncStatus.SYNCING
        self.db.commit()

        try:
            access_token = await self._ensure_valid_token(integration)
            records: list[dict] = []

            if integration.provider == CRMProvider.HUBSPOT:
                service = HubSpotCRMService(access_token)
                records = await service.fetch_contacts_with_deals()
            elif integration.provider == CRMProvider.SALESFORCE:
                service = SalesforceCRMService(access_token, integration.instance_url or "")
                records = await service.fetch_leads()

            imported = self._upsert_leads(organization_id, records)
            integration.sync_status = SyncStatus.SUCCESS
            integration.last_sync_at = datetime.now(UTC)
            self.db.commit()
            return imported
        except Exception as exc:
            integration.sync_status = SyncStatus.FAILED
            self.db.commit()
            logger.exception("CRM sync failed for org %s: %s", organization_id, exc)
            raise

    def _get_integration(self, organization_id: UUID) -> CRMIntegration | None:
        stmt = select(CRMIntegration).where(
            CRMIntegration.organization_id == organization_id,
            CRMIntegration.provider.in_([CRMProvider.HUBSPOT, CRMProvider.SALESFORCE]),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    async def _ensure_valid_token(self, integration: CRMIntegration) -> str:
        access_token = token_encryption.decrypt(integration.access_token_encrypted)
        if integration.expires_at and integration.expires_at <= datetime.now(UTC) + timedelta(minutes=5):
            if integration.provider == CRMProvider.HUBSPOT and integration.refresh_token_encrypted:
                refresh = token_encryption.decrypt(integration.refresh_token_encrypted)
                service = HubSpotCRMService(access_token)
                tokens = await service.refresh_token(refresh)
                integration.access_token_encrypted = token_encryption.encrypt(tokens["access_token"])
                integration.refresh_token_encrypted = token_encryption.encrypt(tokens.get("refresh_token", refresh))
                integration.expires_at = datetime.now(UTC) + timedelta(seconds=tokens.get("expires_in", 3600))
                self.db.commit()
                access_token = tokens["access_token"]
        return access_token

    def _upsert_leads(self, organization_id: UUID, records: list[dict]) -> int:
        count = 0
        for record in records:
            crm_id = record.get("crm_lead_id")
            existing = None
            if crm_id:
                stmt = select(Lead).where(
                    Lead.organization_id == organization_id,
                    Lead.crm_lead_id == crm_id,
                )
                existing = self.db.execute(stmt).scalar_one_or_none()

            last_contact = record.get("last_contact_date")
            if isinstance(last_contact, str):
                try:
                    last_contact = datetime.fromisoformat(last_contact.replace("Z", "+00:00"))
                except ValueError:
                    last_contact = None

            if existing:
                existing.full_name = record.get("full_name") or existing.full_name
                existing.email = record.get("email") or existing.email
                existing.phone = record.get("phone") or existing.phone
                existing.company = record.get("company") or existing.company
                existing.deal_value = record.get("deal_value") or existing.deal_value
                existing.pipeline_stage = record.get("pipeline_stage") or existing.pipeline_stage
                existing.last_contact_date = last_contact or existing.last_contact_date
                existing.notes = record.get("notes") or existing.notes
            else:
                lead = Lead(
                    organization_id=organization_id,
                    crm_lead_id=crm_id,
                    full_name=record.get("full_name") or "Unknown",
                    email=record.get("email"),
                    phone=record.get("phone"),
                    company=record.get("company"),
                    deal_value=record.get("deal_value"),
                    pipeline_stage=record.get("pipeline_stage"),
                    last_contact_date=last_contact,
                    notes=record.get("notes"),
                    lead_status=LeadStatus.ACTIVE,
                )
                self.db.add(lead)
                count += 1

        self.db.commit()
        return count

    def upsert_lead_from_webhook(self, organization_id: UUID, payload: dict) -> Lead:
        crm_id = str(payload.get("objectId") or payload.get("id", ""))
        props = payload.get("properties", payload)

        stmt = select(Lead).where(Lead.organization_id == organization_id, Lead.crm_lead_id == crm_id)
        lead = self.db.execute(stmt).scalar_one_or_none()

        full_name = props.get("full_name") or f"{props.get('firstname', '')} {props.get('lastname', '')}".strip()
        if lead:
            lead.full_name = full_name or lead.full_name
            lead.email = props.get("email") or lead.email
            lead.pipeline_stage = props.get("dealstage") or props.get("pipeline_stage") or lead.pipeline_stage
        else:
            lead = Lead(
                organization_id=organization_id,
                crm_lead_id=crm_id,
                full_name=full_name or "Unknown",
                email=props.get("email"),
                phone=props.get("phone"),
                pipeline_stage=props.get("dealstage"),
                lead_status=LeadStatus.ACTIVE,
            )
            self.db.add(lead)

        self.db.commit()
        self.db.refresh(lead)
        return lead
