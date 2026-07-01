"""Agent execution tracking and deduplication."""

import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.db.models.agent_run import AgentRun, AgentRunStatus


class AgentRunLogger:
    def __init__(self, db: Session, organization_id: UUID, agent_name: str, celery_task_id: str | None = None):
        self.db = db
        self.organization_id = organization_id
        self.agent_name = agent_name
        self.celery_task_id = celery_task_id
        self._run: AgentRun | None = None
        self._start: float = 0

    def start(self, metadata: dict | None = None) -> AgentRun:
        self._start = time.perf_counter()
        self._run = AgentRun(
            organization_id=self.organization_id,
            agent_name=self.agent_name,
            status=AgentRunStatus.RUNNING,
            celery_task_id=self.celery_task_id,
            metadata_json=json.dumps(metadata or {}),
        )
        self.db.add(self._run)
        self.db.commit()
        self.db.refresh(self._run)
        return self._run

    def complete(self, metadata: dict | None = None) -> AgentRun:
        if not self._run:
            raise RuntimeError("Agent run not started")
        elapsed_ms = int((time.perf_counter() - self._start) * 1000)
        self._run.status = AgentRunStatus.COMPLETED
        self._run.execution_time_ms = elapsed_ms
        self._run.completed_at = datetime.now(UTC)
        if metadata:
            self._run.metadata_json = json.dumps(metadata)
        self.db.commit()
        self.db.refresh(self._run)
        return self._run

    def fail(self, error: str) -> AgentRun:
        if not self._run:
            raise RuntimeError("Agent run not started")
        elapsed_ms = int((time.perf_counter() - self._start) * 1000)
        self._run.status = AgentRunStatus.FAILED
        self._run.execution_time_ms = elapsed_ms
        self._run.completed_at = datetime.now(UTC)
        self._run.error_message = error[:4000]
        self.db.commit()
        self.db.refresh(self._run)
        return self._run


def has_recent_run(
    db: Session,
    organization_id: UUID,
    agent_name: str,
    within_minutes: int = 30,
) -> bool:
    """Prevent duplicate agent execution within a time window."""
    from datetime import timedelta
    from sqlalchemy import select

    cutoff = datetime.now(UTC) - timedelta(minutes=within_minutes)
    stmt = (
        select(AgentRun.id)
        .where(
            AgentRun.organization_id == organization_id,
            AgentRun.agent_name == agent_name,
            AgentRun.status.in_([AgentRunStatus.RUNNING, AgentRunStatus.COMPLETED]),
            AgentRun.started_at >= cutoff,
        )
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none() is not None


@contextmanager
def agent_execution(db: Session, organization_id: UUID, agent_name: str, celery_task_id: str | None = None):
    logger = AgentRunLogger(db, organization_id, agent_name, celery_task_id)
    run = logger.start()
    try:
        yield logger
        logger.complete()
    except Exception as exc:
        logger.fail(str(exc))
        raise
