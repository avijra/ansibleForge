"""Galaxy collection management API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.api.schemas.requests import CollectionInstallRequest
from ansible_forge.api.schemas.responses import CollectionResponse
from ansible_forge.tools.galaxy_manager import GalaxyManager

router = APIRouter()


@router.get("/collections/search", response_model=CollectionResponse)
async def search_collections(
    query: str = "",
    _: Any = Depends(verify_api_key),
) -> CollectionResponse:
    mgr = GalaxyManager()
    result = await mgr.execute(action="search", collection_name=query)
    return CollectionResponse(
        status=result.status.value,
        message=result.output,
        collections=result.data.get("collections", []),
    )


@router.post("/collections/install", response_model=CollectionResponse)
async def install_collection(
    request: CollectionInstallRequest,
    _: Any = Depends(verify_api_key),
) -> CollectionResponse:
    mgr = GalaxyManager()
    result = await mgr.execute(
        action="install",
        collection_name=request.name,
        version=request.version or "",
    )
    return CollectionResponse(
        status=result.status.value,
        message=result.output,
    )


@router.get("/collections", response_model=CollectionResponse)
async def list_collections(
    _: Any = Depends(verify_api_key),
) -> CollectionResponse:
    mgr = GalaxyManager()
    result = await mgr.execute(action="list")
    return CollectionResponse(
        status=result.status.value,
        message=result.output,
        collections=result.data.get("collections", []),
    )
