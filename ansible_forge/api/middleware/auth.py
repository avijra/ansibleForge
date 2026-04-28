"""API key authentication middleware."""

from __future__ import annotations

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from ansible_forge.config import get_settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(_api_key_header)) -> str | None:
    """Verify the API key if one is configured.

    If ANSIBLEFORGE_API_KEY is empty/unset, authentication is disabled.
    """
    settings = get_settings()
    if not settings.api_key:
        return None

    if api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key
