"""Inventory sources API — CRUD, refresh, and cloud template endpoints."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ansible_forge.inventory.templates import get_template, list_templates
from ansible_forge.persistence.infrastructure_store import InfrastructureStore
from ansible_forge.tools.inventory_discovery import InventoryDiscoveryTool

router = APIRouter(prefix="/inventory-sources", tags=["inventory-sources"])

_discovery_tool = InventoryDiscoveryTool()


def _store() -> InfrastructureStore:
    return InfrastructureStore.get_instance()


class SourceCreate(BaseModel):
    name: str
    plugin_type: str
    config_yaml: str = ""
    regions: list[str] = []


class SourceUpdate(BaseModel):
    name: str | None = None
    plugin_type: str | None = None
    config_yaml: str | None = None
    regions: list[str] | None = None


class RefreshResult(BaseModel):
    discovered: int = 0
    new: int = 0
    removed: int = 0
    groups: list[str] = []
    error: str | None = None


@router.get("/")
def list_sources() -> list[dict[str, Any]]:
    return _store().list_sources()


@router.post("/")
def create_source(body: SourceCreate) -> dict[str, Any]:
    config_yaml = body.config_yaml
    if not config_yaml:
        tmpl = get_template(body.plugin_type)
        if tmpl:
            config_yaml = tmpl["default_config"]
        else:
            raise HTTPException(
                status_code=422,
                detail=f"No template for '{body.plugin_type}'. Provide config_yaml.",
            )

    source_id = re.sub(r"[^a-zA-Z0-9_-]", "_", body.name.lower())
    store = _store()
    store.upsert_source(
        source_id=source_id,
        name=body.name,
        plugin_type=body.plugin_type,
        config_yaml=config_yaml,
        regions=body.regions,
    )
    source = store.get_source(source_id)
    if not source:
        raise HTTPException(status_code=500, detail="Failed to create source")
    return source


@router.get("/{source_id}")
def get_source(source_id: str) -> dict[str, Any]:
    source = _store().get_source(source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.patch("/{source_id}")
def update_source(source_id: str, body: SourceUpdate) -> dict[str, Any]:
    store = _store()
    existing = store.get_source(source_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Source not found")

    store.upsert_source(
        source_id=source_id,
        name=body.name if body.name is not None else existing["name"],
        plugin_type=body.plugin_type if body.plugin_type is not None else existing["plugin_type"],
        config_yaml=body.config_yaml if body.config_yaml is not None else existing["config_yaml"],
        regions=body.regions if body.regions is not None else existing["regions"],
    )
    return store.get_source(source_id) or existing


@router.delete("/{source_id}")
def delete_source(source_id: str, remove_hosts: bool = False) -> dict[str, str]:
    if not _store().delete_source(source_id, remove_hosts=remove_hosts):
        raise HTTPException(status_code=404, detail="Source not found")
    return {"status": "deleted"}


@router.post("/{source_id}/refresh")
async def refresh_source(source_id: str) -> RefreshResult:
    loop = asyncio.get_running_loop()
    store = _store()
    source = await loop.run_in_executor(None, store.get_source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    result = await _discovery_tool.execute(
        plugin_type=source["plugin_type"],
        config_yaml=source["config_yaml"],
        source_name=source["name"],
    )

    if result.error:
        return RefreshResult(error=result.error)

    return RefreshResult(
        discovered=result.data.get("discovered", 0),
        new=result.data.get("new", 0),
        removed=result.data.get("removed", 0),
        groups=result.data.get("groups", []),
    )


@router.get("/templates/list")
def get_templates() -> list[dict[str, Any]]:
    return list_templates()


@router.get("/templates/{plugin_type:path}")
def get_template_detail(plugin_type: str) -> dict[str, Any]:
    tmpl = get_template(plugin_type)
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"No template for '{plugin_type}'")
    return tmpl
