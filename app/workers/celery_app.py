import logging

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings
from app.core.sentry import init_sentry

settings = get_settings()
init_sentry()

logger = logging.getLogger(__name__)

celery_app = Celery(
    "revio_ai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks.agent_tasks", "app.workers.tasks.scheduler_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=60,
    task_max_retries=3,
    task_routes={
        "app.workers.tasks.agent_tasks.run_revive_agent_task": {"queue": "revive"},
        "app.workers.tasks.agent_tasks.run_pulse_agent_task": {"queue": "pulse"},
        "app.workers.tasks.agent_tasks.run_scout_agent_task": {"queue": "scout"},
        "app.workers.tasks.agent_tasks.run_message_agent_task": {"queue": "message"},
        "app.workers.tasks.agent_tasks.run_execution_agent_task": {"queue": "execution"},
        "app.workers.tasks.agent_tasks.run_response_agent_task": {"queue": "response"},
        "app.workers.tasks.agent_tasks.run_report_agent_task": {"queue": "report"},
        "app.workers.tasks.agent_tasks.run_orchestrator_pipeline_task": {"queue": "orchestrator"},
        "app.workers.tasks.scheduler_tasks.*": {"queue": "scheduler"},
    },
    beat_schedule={
        "revive-agent-daily-9am": {
            "task": "app.workers.tasks.scheduler_tasks.schedule_revive_all",
            "schedule": crontab(hour=9, minute=0),
        },
        "pulse-agent-every-2-hours": {
            "task": "app.workers.tasks.scheduler_tasks.schedule_pulse_all",
            "schedule": crontab(minute=0, hour="*/2"),
        },
        "scout-agent-daily-6am": {
            "task": "app.workers.tasks.scheduler_tasks.schedule_scout_all",
            "schedule": crontab(hour=6, minute=0),
        },
        "report-agent-daily-7am": {
            "task": "app.workers.tasks.scheduler_tasks.schedule_report_all",
            "schedule": crontab(hour=7, minute=0),
        },
        "response-agent-polling-5min": {
            "task": "app.workers.tasks.scheduler_tasks.schedule_response_all",
            "schedule": crontab(minute="*/5"),
        },
    },
)
