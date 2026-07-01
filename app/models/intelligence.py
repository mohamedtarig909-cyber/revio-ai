"""
Intelligence-layer models — canonical import path for the reasoning agents.

The smart Layer-2 agents (planner / conversational / memory) and the reasoning
tools import their models from here:  `from app.models.intelligence import ...`

During migration these are re-exported from the repo-root modules `intelligence.py`
and `autonomous.py` (both on PYTHONPATH=/app in the Docker image). This makes every
`app.models.intelligence` import resolve so the agents run.

TODO (full consolidation): move the class definitions out of the two root modules
into this package and rebind them to the shared `app.db.base.Base`, so Alembic
autogenerate sees them alongside the app/db/models tables. Tracked as a cleanup step.
"""
from __future__ import annotations

# Core intelligence models
from app.models._intelligence_defs import (  # noqa: F401
    ChannelType,
    ConversationStatus,
    IntentType,
    PatternType,
    ExecutionPlan,
    StrategyOutcome,
    StrategyPattern,
    ConversationSession,
    HistoricalCase,
)

# Autonomous / reinforcement-learning models
from app.models._autonomous_defs import (  # noqa: F401
    CycleStatus,
    OverrideTrigger,
    StrategyCycle,
    LeadWorldState,
    StrategyExperiment,
    StrategyScore,
    OverrideEvent,
    RevenueForensics,
    ExperimentAssignment,
)

__all__ = [
    "ChannelType", "ConversationStatus", "IntentType", "PatternType",
    "ExecutionPlan", "StrategyOutcome", "StrategyPattern", "ConversationSession",
    "HistoricalCase",
    "CycleStatus", "OverrideTrigger", "StrategyCycle", "LeadWorldState",
    "StrategyExperiment", "StrategyScore", "OverrideEvent", "RevenueForensics",
    "ExperimentAssignment",
]
