import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.config import get_settings


def init_sentry() -> None:
    settings = get_settings()
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        traces_sample_rate=0.2 if settings.app_env == "production" else 1.0,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            CeleryIntegration(),
            SqlalchemyIntegration(),
        ],
        send_default_pii=False,
    )
