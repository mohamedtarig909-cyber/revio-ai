import logging
from uuid import UUID

from celery import shared_task
from tenacity import retry, stop_after_attempt, wait_exponential

from app.db.session import SyncSessionLocal
from app.orchestrator.engine import OrchestratorEngine

logger = logging.getLogger(__name__)


def _get_db():
    return SyncSessionLocal()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=60))
def _run_with_retry(fn, organization_id: str, task_id: str | None = None):
    db = _get_db()
    try:
        return fn(db, UUID(organization_id), task_id)
    finally:
        db.close()


@shared_task(bind=True, name="app.workers.tasks.agent_tasks.run_revive_agent_task", max_retries=3)
def run_revive_agent_task(self, organization_id: str):
    from app.agents.revive_agent import ReviveAgent
    from app.orchestrator.engine import OrchestratorEngine

    db = _get_db()
    try:
        result = ReviveAgent(db).run(UUID(organization_id), self.request.id)
        lead_ids = [UUID(lid) for lid in result.get("high_probability_lead_ids", [])]
        if lead_ids and not result.get("skipped"):
            OrchestratorEngine(db).trigger_post_revive_chain(UUID(organization_id), lead_ids)
        return result
    except Exception as exc:
        logger.exception("Revive agent failed")
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


@shared_task(bind=True, name="app.workers.tasks.agent_tasks.run_pulse_agent_task", max_retries=3)
def run_pulse_agent_task(self, organization_id: str):
    from app.agents.pulse_agent import PulseAgent

    try:
        return _run_with_retry(lambda db, org_id, tid: PulseAgent(db).run(org_id, tid), organization_id, self.request.id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, name="app.workers.tasks.agent_tasks.run_scout_agent_task", max_retries=3)
def run_scout_agent_task(self, organization_id: str):
    from app.agents.scout_agent import ScoutAgent

    try:
        return _run_with_retry(lambda db, org_id, tid: ScoutAgent(db).run(org_id, tid), organization_id, self.request.id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, name="app.workers.tasks.agent_tasks.run_message_agent_task", max_retries=3)
def run_message_agent_task(self, organization_id: str, lead_ids: list[str] | None = None):
    from app.agents.message_agent import MessageAgent

    db = _get_db()
    try:
        ids = [UUID(lid) for lid in lead_ids] if lead_ids else None
        return MessageAgent(db).run(UUID(organization_id), ids, self.request.id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


@shared_task(bind=True, name="app.workers.tasks.agent_tasks.run_execution_agent_task", max_retries=3)
def run_execution_agent_task(self, organization_id: str, lead_ids: list[str] | None = None):
    from app.agents.execution_agent import ExecutionAgent

    db = _get_db()
    try:
        ids = [UUID(lid) for lid in lead_ids] if lead_ids else None
        return ExecutionAgent(db).run(UUID(organization_id), ids, self.request.id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    finally:
        db.close()


@shared_task(bind=True, name="app.workers.tasks.agent_tasks.run_response_agent_task", max_retries=3)
def run_response_agent_task(self, organization_id: str):
    from app.agents.response_agent import ResponseAgent

    try:
        return _run_with_retry(lambda db, org_id, tid: ResponseAgent(db).run(org_id, tid), organization_id, self.request.id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, name="app.workers.tasks.agent_tasks.run_report_agent_task", max_retries=3)
def run_report_agent_task(self, organization_id: str):
    from app.agents.response_agent import ReportAgent

    try:
        return _run_with_retry(lambda db, org_id, tid: ReportAgent(db).run(org_id, tid), organization_id, self.request.id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc


@shared_task(bind=True, name="app.workers.tasks.agent_tasks.run_orchestrator_pipeline_task", max_retries=2)
def run_orchestrator_pipeline_task(self, organization_id: str):
    db = _get_db()
    try:
        return OrchestratorEngine(db).run_full_pipeline(UUID(organization_id), self.request.id)
    except Exception as exc:
        raise self.retry(exc=exc) from exc
    finally:
        db.close()
