"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Users & Organizations ---

class UserResponse(ORMModel):
    id: UUID
    email: str
    name: str
    subscription_status: str
    organization_id: UUID | None
    created_at: datetime


class OrganizationResponse(ORMModel):
    id: UUID
    company_name: str
    subscription_tier: str
    agents_enabled: bool
    auto_send_enabled: bool
    created_at: datetime


# --- Leads ---

class LeadResponse(ORMModel):
    id: UUID
    organization_id: UUID
    crm_lead_id: str | None
    full_name: str
    email: str | None
    phone: str | None
    company: str | None
    deal_value: Decimal | None
    pipeline_stage: str | None
    lead_status: str
    last_contact_date: datetime | None
    assigned_rep: str | None
    priority_score: int
    created_at: datetime
    updated_at: datetime


class LeadDetailResponse(LeadResponse):
    notes: str | None
    latest_analysis: "LeadAnalysisResponse | None" = None


class LeadAnalysisResponse(ORMModel):
    id: UUID
    lead_id: UUID
    recovery_probability: Decimal | None
    reason_lead_died: str | None
    confidence_score: Decimal | None
    recommended_strategy: str | None
    recommended_message: str | None
    analyzed_at: datetime


class LeadListResponse(BaseModel):
    items: list[LeadResponse]
    total: int
    page: int
    page_size: int


# --- Campaigns ---

class CampaignResponse(ORMModel):
    id: UUID
    organization_id: UUID
    lead_id: UUID
    channel: str
    subject_line: str | None
    message_content: str
    status: str
    sent_at: datetime | None
    responded_at: datetime | None


class CampaignSendRequest(BaseModel):
    lead_id: UUID
    channel: str = Field(..., pattern="^(email|sms|whatsapp)$")
    subject_line: str | None = None
    message_content: str | None = None


# --- Reports & Pipeline ---

class DailyReportResponse(ORMModel):
    id: UUID
    organization_id: UUID
    report_content: str
    generated_at: datetime
    emailed_at: datetime | None


class PipelineHealthResponse(ORMModel):
    id: UUID
    organization_id: UUID
    pipeline_health_score: Decimal
    revenue_at_risk: Decimal
    stalled_deals_count: int
    conversion_bottlenecks: str | None
    generated_at: datetime


class DashboardOverviewResponse(BaseModel):
    total_leads: int
    dormant_leads: int
    reactivated_leads: int
    revenue_at_risk: Decimal
    pipeline_health_score: Decimal | None
    campaigns_sent_24h: int
    responses_24h: int
    latest_report: DailyReportResponse | None


# --- Agent Logs ---

class AgentRunResponse(ORMModel):
    id: UUID
    organization_id: UUID
    agent_name: str
    status: str
    execution_time_ms: int | None
    started_at: datetime
    completed_at: datetime | None
    error_message: str | None


class AgentLogListResponse(BaseModel):
    items: list[AgentRunResponse]
    total: int


# --- OAuth ---

class OAuthCallbackRequest(BaseModel):
    code: str
    state: str | None = None


class CSVUploadResponse(BaseModel):
    imported_count: int
    skipped_count: int
    errors: list[str]
