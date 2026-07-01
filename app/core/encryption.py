import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class TokenEncryption:
    """Encrypt/decrypt OAuth tokens and sensitive credentials at rest."""

    def __init__(self) -> None:
        settings = get_settings()
        key = settings.encryption_key.encode()
        if len(key) != 44:
            derived = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
            self._fernet = Fernet(derived)
        else:
            self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        if not plaintext:
            return ""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not ciphertext:
            return ""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt token") from exc


token_encryption = TokenEncryption()
