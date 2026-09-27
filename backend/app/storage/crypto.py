"""Encryption of stored database passwords (Fernet, key from PGB_STUDIO_SECRET_KEY)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class DecryptionError(Exception):
    """The stored secret cannot be decrypted with the current key."""


class SecretBox:
    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise DecryptionError(
                "stored password cannot be decrypted with the current key"
            ) from exc
