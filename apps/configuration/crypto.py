from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    secret_key = str(settings.SECRET_KEY).encode("utf-8")
    digest = hashlib.sha256(secret_key).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return _fernet().encrypt(raw.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    encrypted = (value or "").strip()
    if not encrypted:
        return ""
    try:
        return _fernet().decrypt(encrypted.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ImproperlyConfigured(
            "A stored payment secret cannot be decrypted. Re-enter the payment gateway secrets in Django Admin."
        ) from exc
