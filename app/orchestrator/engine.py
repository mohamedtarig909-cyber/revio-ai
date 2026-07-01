import asyncio
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.base import AgentRunLogger
from app.agents.execution_agent import ExecutionAgent
from app.agents.message_agent import MessageAgent
from app.agents.revive_agent import ReviveAgent
from app.db.models.agent_run import AgentName
from app.db.models.organization import Organization
from app.services.crm.crm_service import CRMSyncService

logger = logging.getLogger(__name__)


class OrchestratorEngine:
    """
    Central orchestration engine coordinating agent execution order.
    Workflow: CRM sync → REVIVE → MESSAGE → EXECUTION
    """

    AGENT_NAME = AgentName.ORCHESTRATOR

    def __init__(self, db: Session) -> None:
        self.db = db
        self.crm_sync = CRMSyncService(db)
        self.revive = ReviveAgent(db)
        self.message = MessageAgent(db)
        self.execution = ExecutionAgent(db)

    def run_full_pipeline(self, organization_id: UUID, celery_task_id: str | None = None) -> dict:
        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled:
            return {"skipped": True, "reason": "agents_disabled"}

        run_logger = AgentRunLogger(self.db, organization_id, self.AGENT_NAME, celery_task_id)
        run_logger.start({"pipeline": "full"})

        pipeline_result: dict = {"organization_id": str(organization_id), "steps": []}

        try:
            synced = asyncio.run(self.crm_sync.sync_organization(organization_id))
            pipeline_result["steps"].append({"crm_sync": {"imported": synced}})

            revive_result = self.revive.run(organization_id, celery_task_id)
            pipeline_result["steps"].append({"revive": revive_result})

            lead_ids = [UUID(lid) for lid in revive_result.get("high_probability_lead_ids", [])]
            if lead_ids:
                message_result = self.message.run(organization_id, lead_ids, celery_task_id)
                pipeline_result["steps"].append({"message": message_result})

                if org.auto_send_enabled:
                    execution_result = self.execution.run(organization_id, lead_ids, celery_task_id)
                    pipeline_result["steps"].append({"execution": execution_result})

            run_logger.complete(pipeline_result)
            return pipeline_result
        except Exception as exc:
            run_logger.fail(str(exc))
            logger.exception("Orchestrator pipeline failed for org %s", organization_id)
            raise

    def run_for_all_organizations(self) -> dict:
        orgs = self.db.execute(
            select(Organization).where(Organization.agents_enabled.is_(True))
        ).scalars().all()

        results = []
        for org in orgs:
            try:
                result = self.run_full_pipeline(org.id)
                results.append({"org_id": str(org.id), "status": "success", "result": result})
            except Exception as exc:
                results.append({"org_id": str(org.id), "status": "failed", "error": str(exc)})

        return {"organizations_processed": len(results), "results": results}

    def trigger_post_revive_chain(self, organization_id: UUID, lead_ids: list[UUID]) -> dict:
        """Called after REVIVE agent completes to chain MESSAGE → EXECUTION."""
        org = self.db.get(Organization, organization_id)
        if not org or not org.agents_enabled:
            return {"skipped": True}

        message_result = self.message.run(organization_id, lead_ids)
        execution_result = {}
        if org.auto_send_enabled:
            execution_result = self.execution.run(organization_id, lead_ids)

        return {"message": message_result, "execution": execution_result}

    def schedule_reanalysis(self, organization_id: UUID) -> None:
        """Schedule re-analysis after CRM webhook event."""
        from app.workers.tasks.agent_tasks import run_revive_agent_task

        run_revive_agent_task.delay(str(organization_id))
