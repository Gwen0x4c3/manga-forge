from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

_ENC_PREFIX = "enc:v1:"


def _get_fernet() -> Fernet:
    seed = (
        getattr(settings, "APP_SECRET_KEY", "")
        or f"mangaforge-key-v1:{settings.MYSQL_HOST}:{settings.MYSQL_DATABASE}:{settings.MYSQL_USER}"
    )
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(raw: str | None) -> str | None:
    if not raw or not raw.strip():
        return None
    val = raw.strip()
    if val.startswith(_ENC_PREFIX):
        return val
    token = _get_fernet().encrypt(val.encode("utf-8")).decode("ascii")
    return f"{_ENC_PREFIX}{token}"


def decrypt_secret(stored: str | None) -> str:
    if not stored:
        return ""
    if not stored.startswith(_ENC_PREFIX):
        return stored
    token = stored[len(_ENC_PREFIX) :]
    try:
        return _get_fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.warning("Failed to decrypt stored API key; returning empty string")
        return ""


def mask_api_key(raw: str | None) -> str:
    val = (raw or "").strip()
    if not val:
        return ""
    if len(val) <= 8:
        return "*" * len(val)
    return f"{val[:4]}••••{val[-4:]}"
