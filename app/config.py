from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Revio AI"
    app_env: str = "production"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    secret_key: str
    encryption_key: str

    database_url: str
    database_url_sync: str

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter: str = ""
    stripe_price_growth: str = ""
    stripe_price_enterprise: str = ""

    hubspot_client_id: str = ""
    hubspot_client_secret: str = ""
    hubspot_redirect_uri: str = ""
    hubspot_webhook_secret: str = ""

    salesforce_client_id: str = ""
    salesforce_client_secret: str = ""
    salesforce_redirect_uri: str = ""

    llm_provider: Literal["openai", "anthropic"] = "openai"
    openai_api_key: str = ""
    # OpenAI-compatible gateway base. For OpenRouter set:
    #   OPENAI_BASE_URL=https://openrouter.ai/api/v1
    #   OPENAI_API_KEY=sk-or-...   LLM_MODEL=openai/gpt-4o  LLM_MODEL_SMALL=openai/gpt-4o-mini
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = ""
    llm_model: str = "gpt-4o"
    llm_model_small: str = "gpt-4o-mini"   # cheap tasks (builder previews, classification)

    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "revive@revio.ai"
    resend_api_key: str = ""
    resend_from_email: str = "reports@revio.ai"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    apollo_api_key: str = ""
    crunchbase_api_key: str = ""
    slack_webhook_url: str = ""

    sentry_dsn: str = ""

    admin_token: str = ""   # gate for the /api/v1/admin control panel
    google_client_id: str = ""   # Google OAuth web client id (Sign in with Google)
    whop_webhook_secret: str = ""   # verify Whop webhook signatures

    revive_inactivity_days: int = 30
    pulse_revenue_risk_threshold: float = 50000.0
    auto_send_enabled: bool = False   # compliance: no auto-send until suppression/opt-out exists

    cors_origins: list[str] = Field(default_factory=lambda: ["https://app.revio.ai"])


@lru_cache
def get_settings() -> Settings:
    return Settings()
