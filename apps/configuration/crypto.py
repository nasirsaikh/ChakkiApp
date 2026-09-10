from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _fernet() -> Fernet:
    # Keep SECRET_KEY as a backward-compatible fallback so existing encrypted
    # gateway credentials remain readable until PAYMENT_ENCRYPTION_KEY is set.
    encryption_key = os.getenv("PAYMENT_ENCRYPTION_KEY") or str(settings.SECRET_KEY)
    digest = hashlib.sha256(encryption_key.encode("utf-8")).digest()
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
