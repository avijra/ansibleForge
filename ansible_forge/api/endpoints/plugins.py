"""Plugin management API — list installed plugins and their tools."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.plugins.loader import list_installed_plugins

router = APIRouter()


@router.get("/plugins")
async def get_plugins(
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    plugins = list_installed_plugins()
    return {
        "plugins": plugins,
        "total": len(plugins),
    }
