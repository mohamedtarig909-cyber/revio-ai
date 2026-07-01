import logging
from io import StringIO
from uuid import UUID

import pandas as pd
from sqlalchemy.orm import Session

from app.db.models.crm_integration import CRMIntegration, CRMProvider, SyncStatus
from app.db.models.lead import Lead, LeadStatus

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {"full_name"}
OPTIONAL_COLUMNS = {
    "email", "phone", "company", "deal_value", "pipeline_stage",
    "last_contact_date", "assigned_rep", "notes", "crm_lead_id",
}


class CSVImportService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def import_csv(self, organization_id: UUID, file_content: bytes) -> dict:
        errors: list[str] = []
        imported = 0
        skipped = 0

        try:
            df = pd.read_csv(StringIO(file_content.decode("utf-8-sig")))
        except Exception as exc:
            return {"imported_count": 0, "skipped_count": 0, "errors": [f"Invalid CSV: {exc}"]}

        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        missing = REQUIRED_COLUMNS - set(df.columns)
        if missing:
            return {"imported_count": 0, "skipped_count": 0, "errors": [f"Missing columns: {missing}"]}

        integration = CRMIntegration(
            organization_id=organization_id,
            provider=CRMProvider.CSV,
            access_token_encrypted="",
            sync_status=SyncStatus.SUCCESS,
        )
        self.db.add(integration)

        for idx, row in df.iterrows():
            full_name = str(row.get("full_name", "")).strip()
            if not full_name or full_name == "nan":
                skipped += 1
                continue

            try:
                deal_value = row.get("deal_value")
                if pd.notna(deal_value):
                    deal_value = float(deal_value)
                else:
                    deal_value = None

                lead = Lead(
                    organization_id=organization_id,
                    crm_lead_id=str(row.get("crm_lead_id")) if pd.notna(row.get("crm_lead_id")) else None,
                    full_name=full_name,
                    email=str(row["email"]).strip() if pd.notna(row.get("email")) else None,
                    phone=str(row["phone"]).strip() if pd.notna(row.get("phone")) else None,
                    company=str(row["company"]).strip() if pd.notna(row.get("company")) else None,
                    deal_value=deal_value,
                    pipeline_stage=str(row["pipeline_stage"]).strip() if pd.notna(row.get("pipeline_stage")) else None,
                    assigned_rep=str(row["assigned_rep"]).strip() if pd.notna(row.get("assigned_rep")) else None,
                    notes=str(row["notes"]).strip() if pd.notna(row.get("notes")) else None,
                    lead_status=LeadStatus.ACTIVE,
                )
                self.db.add(lead)
                imported += 1
            except Exception as exc:
                errors.append(f"Row {idx + 2}: {exc}")
                skipped += 1

        self.db.commit()
        return {"imported_count": imported, "skipped_count": skipped, "errors": errors[:20]}
