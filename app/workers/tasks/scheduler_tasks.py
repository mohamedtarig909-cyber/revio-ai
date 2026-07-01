import logging

from celery import shared_task
from sqlalchemy import select

from app.db.models.organization import Organization
from app.db.session import SyncSessionLocal
from app.workers.tasks.agent_tasks import (
    run_pulse_agent_task,
    run_report_agent_task,
    run_response_agent_task,
    run_revive_agent_task,
    run_scout_agent_task,
)

logger = logging.getLogger(__name__)


def _get_active_org_ids() -> list[str]:
    db = SyncSessionLocal()
    try:
        orgs = db.execute(select(Organization).where(Organization.agents_enabled.is_(True))).scalars().all()
        return [str(org.id) for org in orgs]
    finally:
        db.close()


@shared_task(name="app.workers.tasks.scheduler_tasks.schedule_revive_all")
def schedule_revive_all():
    org_ids = _get_active_org_ids()
    for org_id in org_ids:
        run_revive_agent_task.delay(org_id)
    logger.info("Scheduled REVIVE agent for %d organizations", len(org_ids))
    return {"scheduled": len(org_ids)}


@shared_task(name="app.workers.tasks.scheduler_tasks.schedule_pulse_all")
def schedule_pulse_all():
    org_ids = _get_active_org_ids()
    for org_id in org_ids:
        run_pulse_agent_task.delay(org_id)
    return {"scheduled": len(org_ids)}


@shared_task(name="app.workers.tasks.scheduler_tasks.schedule_scout_all")
def schedule_scout_all():
    org_ids = _get_active_org_ids()
    for org_id in org_ids:
        run_scout_agent_task.delay(org_id)
    return {"scheduled": len(org_ids)}


@shared_task(name="app.workers.tasks.scheduler_tasks.schedule_report_all")
def schedule_report_all():
    org_ids = _get_active_org_ids()
    for org_id in org_ids:
        run_report_agent_task.delay(org_id)
    return {"scheduled": len(org_ids)}


@shared_task(name="app.workers.tasks.scheduler_tasks.schedule_response_all")
def schedule_response_all():
    org_ids = _get_active_org_ids()
    for org_id in org_ids:
        run_response_agent_task.delay(org_id)
    return {"scheduled": len(org_ids)}
