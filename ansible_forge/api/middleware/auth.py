"""API key and JWT bearer authentication middleware."""

from __future__ import annotations

import hmac
import json
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from ansible_forge.config import get_settings
from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)


def _pad_b64(s: str) -> str:
    return s + "=" * (-len(s) % 4)


def _verify_hs256_jwt(token: str, secret: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("malformed token")
    header_b, payload_b, sig_b = parts
    expected = hmac.new(
        secret.encode(), f"{header_b}.{payload_b}".encode(), sha256
    ).digest()
    actual = urlsafe_b64decode(_pad_b64(sig_b))
    if not hmac.compare_digest(expected, actual):
        raise ValueError("invalid signature")
    payload = json.loads(urlsafe_b64decode(_pad_b64(payload_b)))
    if payload.get("exp") and payload["exp"] < time.time():
        raise ValueError("token expired")
    return payload


def create_jwt(subject: str, role: str = "operator", ttl: int = 86400) -> str:
    """Issue an HS256 JWT signed with ANSIBLEFORGE_JWT_SECRET."""
    settings = get_settings()
    if not settings.jwt_secret:
        raise RuntimeError("ANSIBLEFORGE_JWT_SECRET is not configured")
    header = urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    payload = urlsafe_b64encode(json.dumps({
        "sub": subject,
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + ttl,
    }).encode()).rstrip(b"=").decode()
    sig = urlsafe_b64encode(
        hmac.new(settings.jwt_secret.encode(), f"{header}.{payload}".encode(), sha256).digest()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.{sig}"


async def verify_api_key(
    api_key: str | None = Security(_api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer),
) -> str | None:
    """Verify API key or JWT bearer token.

    Authentication is disabled when neither ANSIBLEFORGE_API_KEY nor
    ANSIBLEFORGE_JWT_SECRET is set.
    """
    settings = get_settings()

    if not settings.api_key and not settings.jwt_secret:
        return None

    if api_key and settings.api_key and api_key == settings.api_key:
        return api_key

    if bearer and settings.jwt_secret:
        try:
            payload = _verify_hs256_jwt(bearer.credentials, settings.jwt_secret)
            return payload.get("sub", "jwt-user")
        except (ValueError, Exception):
            logger.debug("jwt_verify_failed", exc_info=True)

    raise HTTPException(status_code=401, detail="Invalid or missing credentials")
