import logging

from twilio.rest import Client

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class SMSService:
    def __init__(self) -> None:
        if settings.twilio_account_sid and settings.twilio_auth_token:
            self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        else:
            self._client = None

    def send_sms(self, to_number: str, body: str) -> str:
        if not self._client:
            raise RuntimeError("Twilio not configured")
        if not settings.twilio_from_number:
            raise RuntimeError("Twilio from number not configured")

        message = self._client.messages.create(
            body=body[:1600],
            from_=settings.twilio_from_number,
            to=to_number,
        )
        logger.info("SMS sent to %s sid=%s", to_number, message.sid)
        return message.sid
