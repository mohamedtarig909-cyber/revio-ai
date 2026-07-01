import logging

import httpx
import resend
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EmailService:
    """Outbound email via SendGrid; transactional reports via Resend."""

    def send_via_sendgrid(
        self,
        to_email: str,
        subject: str,
        html_body: str,
        text_body: str | None = None,
    ) -> str:
        if not settings.sendgrid_api_key:
            raise RuntimeError("SendGrid API key not configured")

        message = Mail(
            from_email=settings.sendgrid_from_email,
            to_emails=to_email,
            subject=subject,
            html_content=html_body,
            plain_text_content=text_body or html_body,
        )
        client = SendGridAPIClient(settings.sendgrid_api_key)
        response = client.send(message)
        message_id = response.headers.get("X-Message-Id", "")
        logger.info("SendGrid email sent to %s message_id=%s", to_email, message_id)
        return message_id

    def send_via_resend(
        self,
        to_email: str,
        subject: str,
        html_body: str,
    ) -> str:
        if not settings.resend_api_key:
            raise RuntimeError("Resend API key not configured")

        resend.api_key = settings.resend_api_key
        result = resend.Emails.send(
            {
                "from": settings.resend_from_email,
                "to": [to_email],
                "subject": subject,
                "html": html_body,
            }
        )
        message_id = result.get("id", "") if isinstance(result, dict) else str(result)
        logger.info("Resend email sent to %s message_id=%s", to_email, message_id)
        return message_id

    async def send_welcome_email(self, to_email: str, name: str, company_name: str) -> str:
        subject = "Welcome to Revio AI — Your Revenue Operating System is Live"
        html = f"""
        <h1>Welcome to Revio AI, {name}!</h1>
        <p>Your autonomous revenue intelligence platform is now active for <strong>{company_name}</strong>.</p>
        <p>Revio AI will continuously monitor your pipeline, detect lost revenue, and re-engage dormant leads — automatically.</p>
        <p>Connect your CRM to get started.</p>
        """
        return self.send_via_resend(to_email, subject, html)


class SlackAlertService:
    async def send_alert(self, webhook_url: str, message: str, blocks: list | None = None) -> None:
        payload: dict = {"text": message}
        if blocks:
            payload["blocks"] = blocks

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(webhook_url, json=payload)
            response.raise_for_status()
