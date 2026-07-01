"""
CONVERSATIONAL AGENT — Autonomous multi-turn conversation engine.

Replaces the primitive keyword-detection RESPONSE agent.
Handles:
  - Intent classification (not keyword matching)
  - Objection handling with LLM-generated responses
  - Multi-turn conversation state management
  - Escalation decisions based on confidence thresholds
  - Conversation session lifecycle
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.models.intelligence import ConversationSession, ConversationStatus, IntentType

logger = logging.getLogger(__name__)

OPENAI_API_BASE = "https://api.openai.com/v1"
ESCALATION_CONFIDENCE_THRESHOLD = 0.65
HUMAN_INTENT_CONFIDENCE_THRESHOLD = 0.80

ANALYSIS_SYSTEM_PROMPT = """
You are an expert B2B sales closer with deep expertise in objection handling.

Your job is to:
1. Analyze the customer's reply and determine their exact intent
2. Identify the specific objection type if present
3. Decide whether AI can continue or a human rep is needed
4. Generate the optimal next response

INTENT TYPES:
- price_objection: customer thinks it costs too much
- budget_objection: customer has internal budget constraints
- timing_objection: customer says "not right now" or "next quarter"
- approval_needed: customer needs to check with someone else
- competitor_objection: customer is evaluating competitors
- interest_signal: customer shows genuine interest
- meeting_request: customer wants to schedule a call/demo
- positive: customer is ready to proceed
- negative: customer has decided not to proceed
- unclear: intent cannot be determined

You MUST return valid JSON:
{
  "intent": "<intent_type>",
  "confidence": <float 0.0-1.0>,
  "continue_conversation": <bool>,
  "human_required": <bool>,
  "human_required_reason": "<reason if human_required>",
  "recommended_response": "<the exact message to send to the lead>",
  "objection_addressed": "<summary of how you addressed the objection>",
  "next_stage": "<stage label: initial|objection_handled|interest_confirmed|meeting_scheduled|closed_won|closed_lost|escalated>"
}
"""

RESPONSE_SYSTEM_PROMPT = """
You are a B2B sales expert generating a reply to a lead.

Context provided: conversation history, detected intent, objection type.

Generate a warm, professional, concise response that:
- Directly addresses the lead's specific concern
- Does NOT sound scripted or robotic
- Proposes a clear next step
- Is appropriate for {channel} communication

Return ONLY the message text. No JSON. No preamble.
"""


class ConversationalAgent:
    """
    Manages full conversation lifecycle for a lead.
    """

    def __init__(
        self,
        openai_api_key: str,
        db: AsyncSession,
        escalation_threshold: float = ESCALATION_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._api_key = openai_api_key
        self._db = db
        self._escalation_threshold = escalation_threshold
        self._client = httpx.AsyncClient(timeout=30.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def handle_reply(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        incoming_message: str,
        channel: str = "email",
        execution_plan_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """
        Process an incoming lead reply.
        Returns analysis result + generated response + session state.
        """
        # Load or create session
        session = await self._get_or_create_session(
            organization_id, lead_id, execution_plan_id
        )

        if session.conversation_status in (
            ConversationStatus.CLOSED,
            ConversationStatus.ESCALATED,
        ):
            return {
                "error": f"Session is {session.conversation_status}; cannot process new messages.",
                "session_id": str(session.id),
            }

        # Append incoming message to history
        session.message_history = [
            *(session.message_history or []),
            {
                "role": "lead",
                "content": incoming_message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "channel": channel,
            },
        ]
        session.last_message_at = datetime.now(timezone.utc)

        # Analyze intent
        analysis = await self._analyze_intent(
            message=incoming_message,
            conversation_history=session.message_history,
            current_stage=session.current_stage,
        )

        intent = analysis.get("intent", IntentType.UNCLEAR)
        confidence = float(analysis.get("confidence", 0.0))
        human_required = analysis.get("human_required", False)
        continue_conversation = analysis.get("continue_conversation", True)

        # Track objections
        if intent not in (
            IntentType.POSITIVE,
            IntentType.NEGATIVE,
            IntentType.UNCLEAR,
            IntentType.INTEREST_SIGNAL,
            IntentType.MEETING_REQUEST,
        ):
            objection_history = list(session.objection_history or [])
            if intent not in objection_history:
                objection_history.append(intent)
            session.objection_history = objection_history

        detected_intents = list(session.detected_intents or [])
        detected_intents.append(intent)
        session.detected_intents = detected_intents
        session.current_stage = analysis.get("next_stage", session.current_stage)

        # Decide: escalate, close, or continue
        response_text: str | None = None

        if human_required or confidence < self._escalation_threshold:
            await self._escalate_session(session, analysis.get("human_required_reason", "Low confidence"))
        elif intent == IntentType.NEGATIVE:
            session.conversation_status = ConversationStatus.CLOSED
            session.closed_at = datetime.now(timezone.utc)
        elif intent in (IntentType.POSITIVE, IntentType.MEETING_REQUEST):
            response_text = analysis.get("recommended_response")
            if intent == IntentType.POSITIVE:
                session.current_stage = "closed_won"
                session.conversation_status = ConversationStatus.CLOSED
                session.closed_at = datetime.now(timezone.utc)
        elif continue_conversation:
            # Generate AI response
            response_text = await self._generate_response(
                analysis=analysis,
                conversation_history=session.message_history,
                channel=channel,
            )

        # Append AI response to history
        if response_text:
            session.message_history = [
                *(session.message_history or []),
                {
                    "role": "ai",
                    "content": response_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "channel": channel,
                    "intent_detected": intent,
                    "confidence": confidence,
                },
            ]

        await self._db.flush()
        await self._db.refresh(session)

        return {
            "session_id": str(session.id),
            "intent": intent,
            "confidence": confidence,
            "continue_conversation": continue_conversation,
            "human_required": session.human_required,
            "conversation_status": session.conversation_status,
            "current_stage": session.current_stage,
            "response_text": response_text,
            "analysis": analysis,
            "objection_history": session.objection_history,
        }

    async def get_session(
        self,
        lead_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> ConversationSession | None:
        stmt = (
            select(ConversationSession)
            .where(
                ConversationSession.lead_id == lead_id,
                ConversationSession.organization_id == organization_id,
                ConversationSession.conversation_status == ConversationStatus.ACTIVE,
            )
            .order_by(ConversationSession.created_at.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def close_session(
        self,
        session_id: uuid.UUID,
        reason: str = "manual_close",
    ) -> None:
        stmt = select(ConversationSession).where(ConversationSession.id == session_id)
        result = await self._db.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            session.conversation_status = ConversationStatus.CLOSED
            session.closed_at = datetime.now(timezone.utc)
            session.notes = reason if hasattr(session, "notes") else None
            await self._db.flush()

    # ------------------------------------------------------------------
    # Intent analysis
    # ------------------------------------------------------------------

    async def _analyze_intent(
        self,
        message: str,
        conversation_history: list[dict[str, Any]],
        current_stage: str,
    ) -> dict[str, Any]:
        """LLM-based intent analysis. No keyword matching."""
        history_formatted = self._format_history_for_prompt(conversation_history[-10:])

        user_prompt = f"""
CONVERSATION HISTORY (last 10 messages):
{history_formatted}

CURRENT STAGE: {current_stage}

LATEST CUSTOMER MESSAGE:
"{message}"

Analyze this customer message and return your JSON response.
"""
        raw = await self._call_llm(
            system=ANALYSIS_SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.1,
            response_format={"type": "json_object"},
        )

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Intent analysis JSON parse failed; raw=%s", raw[:300])
            return {
                "intent": IntentType.UNCLEAR,
                "confidence": 0.3,
                "continue_conversation": True,
                "human_required": False,
                "recommended_response": "Thank you for your message. Could you share a bit more?",
                "next_stage": current_stage,
            }

    # ------------------------------------------------------------------
    # Response generation
    # ------------------------------------------------------------------

    async def _generate_response(
        self,
        analysis: dict[str, Any],
        conversation_history: list[dict[str, Any]],
        channel: str,
    ) -> str:
        """Generate the actual message text to send."""
        # Use the recommended_response from analysis as the primary source.
        # If it's good enough (non-empty), return it directly.
        # Otherwise call the LLM for a refined response.
        recommended = analysis.get("recommended_response", "").strip()
        if recommended and len(recommended) > 20:
            return recommended

        history_formatted = self._format_history_for_prompt(conversation_history[-8:])
        system = RESPONSE_SYSTEM_PROMPT.format(channel=channel)
        user = f"""
CONVERSATION HISTORY:
{history_formatted}

DETECTED INTENT: {analysis.get('intent')}
OBJECTION ADDRESSED: {analysis.get('objection_addressed', 'n/a')}
NEXT STAGE TARGET: {analysis.get('next_stage')}

Generate the response message now.
"""
        return await self._call_llm(
            system=system,
            user=user,
            temperature=0.4,
            response_format=None,  # Free text
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _get_or_create_session(
        self,
        organization_id: uuid.UUID,
        lead_id: uuid.UUID,
        execution_plan_id: uuid.UUID | None,
    ) -> ConversationSession:
        existing = await self.get_session(lead_id, organization_id)
        if existing:
            return existing

        session = ConversationSession(
            organization_id=organization_id,
            lead_id=lead_id,
            execution_plan_id=execution_plan_id,
            message_history=[],
            current_stage="initial",
            objection_history=[],
            detected_intents=[],
            conversation_status=ConversationStatus.ACTIVE,
        )
        self._db.add(session)
        await self._db.flush()
        await self._db.refresh(session)
        logger.info("Created ConversationSession: id=%s lead=%s", session.id, lead_id)
        return session

    async def _escalate_session(
        self,
        session: ConversationSession,
        reason: str,
    ) -> None:
        session.human_required = True
        session.escalation_reason = reason
        session.escalated_at = datetime.now(timezone.utc)
        session.conversation_status = ConversationStatus.ESCALATED
        logger.info(
            "Session escalated: id=%s lead=%s reason=%s",
            session.id,
            session.lead_id,
            reason,
        )
        # TODO: Trigger CRM task assignment / Slack notification here

    # ------------------------------------------------------------------
    # LLM helper
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(httpx.HTTPStatusError),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    async def _call_llm(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        response_format: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        response = await self._client.post(
            f"{OPENAI_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_history_for_prompt(history: list[dict[str, Any]]) -> str:
        if not history:
            return "(no previous messages)"
        lines = []
        for msg in history:
            role = "LEAD" if msg.get("role") == "lead" else "AI"
            ts = msg.get("timestamp", "")[:19].replace("T", " ")
            lines.append(f"[{ts}] {role}: {msg.get('content', '')}")
        return "\n".join(lines)

    async def close(self) -> None:
        await self._client.aclose()
