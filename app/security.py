"""Password hashing, JWT, and API-key primitives."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------- passwords ----------
def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd.verify(plain, hashed)


# ---------- JWT (user sessions) ----------
def create_access_token(subject: str, extra: dict | None = None) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError:
        return None


# ---------- API keys ----------
API_KEY_PREFIX = "nk"  # Nakatomi


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, prefix, hash).

    Full key format: ``nk_<prefix>_<secret>``. Only the hash is stored.
    """
    prefix = secrets.token_urlsafe(6).replace("_", "").replace("-", "")[:8]
    secret = secrets.token_urlsafe(32)
    full = f"{API_KEY_PREFIX}_{prefix}_{secret}"
    return full, prefix, hashlib.sha256(full.encode()).hexdigest()


def hash_api_key(full: str) -> str:
    return hashlib.sha256(full.encode()).hexdigest()


def parse_api_key_prefix(full: str) -> str | None:
    parts = full.split("_")
    if len(parts) < 3 or parts[0] != API_KEY_PREFIX:
        return None
    return parts[1]


# ---------- HMAC signing (webhooks) ----------
def hmac_sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------- Application-level secret storage (email IMAP/SMTP passwords) ----------
_STORED_SECRET_PREFIX = "enc:v1:"


def _fernet_key() -> bytes:
    from base64 import urlsafe_b64encode

    digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return urlsafe_b64encode(digest)


def encrypt_stored_secret(plain: str | None) -> str | None:
    """Encrypt a workspace secret for DB storage. Idempotent if already encrypted."""
    if plain is None or plain == "":
        return plain
    if plain.startswith(_STORED_SECRET_PREFIX):
        return plain
    from cryptography.fernet import Fernet

    token = Fernet(_fernet_key()).encrypt(plain.encode()).decode()
    return f"{_STORED_SECRET_PREFIX}{token}"


def decrypt_stored_secret(stored: str | None) -> str | None:
    """Decrypt a stored secret; legacy plaintext values pass through unchanged."""
    if stored is None or stored == "":
        return stored
    if not stored.startswith(_STORED_SECRET_PREFIX):
        return stored
    from cryptography.fernet import Fernet

    token = stored[len(_STORED_SECRET_PREFIX) :].encode()
    return Fernet(_fernet_key()).decrypt(token).decode()
