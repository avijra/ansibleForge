"""Infrastructure store API — persistent host, facts, run history, and drift endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ansible_forge.persistence.infrastructure_store import InfrastructureStore

router = APIRouter(prefix="/infrastructure", tags=["infrastructure"])


def _store() -> InfrastructureStore:
    return InfrastructureStore.get_instance()


class HostCreate(BaseModel):
    hostname: str
    ip_address: str = ""
    groups: list[str] = []
    variables: dict[str, Any] = {}
    connection_type: str = "ssh"
    ansible_user: str = ""


class HostUpdate(BaseModel):
    ip_address: str | None = None
    groups: list[str] | None = None
    variables: dict[str, Any] | None = None
    status: str | None = None
    ansible_user: str | None = None


@router.get("/hosts")
def list_hosts(group: str | None = None) -> list[dict[str, Any]]:
    return _store().list_hosts(group=group)


@router.post("/hosts")
def create_host(body: HostCreate) -> dict[str, Any]:
    host_id = _store().upsert_host(
        hostname=body.hostname,
        ip_address=body.ip_address,
        groups=body.groups,
        variables=body.variables,
        connection_type=body.connection_type,
        ansible_user=body.ansible_user,
    )
    host = _store().get_host(host_id)
    if not host:
        raise HTTPException(status_code=500, detail="Failed to create host")
    return host


@router.get("/hosts/{host_id}")
def get_host(host_id: str) -> dict[str, Any]:
    host = _store().get_host(host_id)
    if not host:
        raise HTTPException(status_code=404, detail="Host not found")
    return host


@router.patch("/hosts/{host_id}")
def update_host(host_id: str, body: HostUpdate) -> dict[str, Any]:
    existing = _store().get_host(host_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Host not found")

    _store().upsert_host(
        hostname=existing["hostname"],
        ip_address=body.ip_address if body.ip_address is not None else existing["ip_address"],
        groups=body.groups if body.groups is not None else existing["groups"],
        variables=body.variables if body.variables is not None else existing["variables"],
        ansible_user=body.ansible_user if body.ansible_user is not None else existing["ansible_user"],
        status=body.status if body.status is not None else existing["status"],
    )
    return _store().get_host(host_id) or existing


@router.delete("/hosts/{host_id}")
def delete_host(host_id: str) -> dict[str, str]:
    if not _store().delete_host(host_id):
        raise HTTPException(status_code=404, detail="Host not found")
    return {"status": "deleted"}


@router.get("/hosts/{host_id}/facts")
def get_host_facts(host_id: str) -> dict[str, Any]:
    facts = _store().get_facts(host_id)
    if not facts:
        raise HTTPException(status_code=404, detail="No facts for this host")
    return facts


@router.get("/hosts/{host_id}/roles")
def get_host_roles(host_id: str) -> list[dict[str, Any]]:
    return _store().get_applied_roles(host_id)


@router.get("/runs")
def list_runs(limit: int = 50, session_id: str | None = None) -> list[dict[str, Any]]:
    return _store().list_runs(limit=limit, session_id=session_id)


@router.get("/drift")
def list_drift(host_id: str | None = None) -> list[dict[str, Any]]:
    return _store().get_unresolved_drift(host_id=host_id)


@router.post("/drift/{drift_id}/resolve")
def resolve_drift(drift_id: int) -> dict[str, str]:
    _store().resolve_drift(drift_id)
    return {"status": "resolved"}


@router.get("/stats")
def infrastructure_stats() -> dict[str, Any]:
    return _store().get_stats()


class InventoryImport(BaseModel):
    content: str
    format: str = "yaml"


@router.post("/import")
def import_inventory(body: InventoryImport) -> dict[str, Any]:
    import yaml as pyyaml

    try:
        data = pyyaml.safe_load(body.content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="Expected YAML dict with groups")

    store = _store()
    imported = 0
    all_section = data.get("all", data)
    hosts_section = all_section.get("hosts", {})
    children = all_section.get("children", {})

    for hostname, hvars in (hosts_section or {}).items():
        hvars = hvars or {}
        store.upsert_host(
            hostname=hostname,
            ip_address=str(hvars.get("ansible_host", "")),
            ansible_user=str(hvars.get("ansible_user", "")),
        )
        imported += 1

    for group_name, group_data in (children or {}).items():
        if not isinstance(group_data, dict):
            continue
        group_hosts = group_data.get("hosts", {})
        for hostname, hvars in (group_hosts or {}).items():
            hvars = hvars or {}
            existing = store.list_hosts()
            existing_ids = {h["hostname"] for h in existing}
            groups = [group_name]
            if hostname in existing_ids:
                for h in existing:
                    if h["hostname"] == hostname:
                        groups = list(set(h["groups"] + [group_name]))
                        break
            store.upsert_host(
                hostname=hostname,
                ip_address=str(hvars.get("ansible_host", "")),
                groups=groups,
                ansible_user=str(hvars.get("ansible_user", "")),
            )
            imported += 1

    return {"imported": imported, "total_hosts": store.get_stats()["hosts"]}
