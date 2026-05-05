"""Experience store API endpoints for stats and learning data."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.knowledge.experience_store import ExperienceStore
from ansible_forge.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

_store: ExperienceStore | None = None


def _get_store() -> ExperienceStore:
    global _store
    if _store is None:
        _store = ExperienceStore()
    return _store


def _build_stats(store: ExperienceStore) -> dict[str, Any]:
    stats = {
        "recipes": store.count("recipe"),
        "error_resolutions": store.count("error_resolution"),
        "corrections": store.count("correction"),
        "reflections": store.count("reflection"),
        "rules": store.count("rule"),
        "total": store.count(),
    }

    recent_errors = []
    for exp in store.query_by_type("error_resolution", limit=10):
        recent_errors.append({
            "pattern": exp.trigger[:100],
            "module": exp.context.get("tool", ""),
            "os_family": "",
            "resolution": exp.solution[:200],
            "resolved": exp.outcome == "resolved",
            "count": exp.use_count,
        })

    return {"stats": stats, "recent_errors": recent_errors}


def _build_graph(store: ExperienceStore) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    type_colors = {
        "recipe": "recipe",
        "error_resolution": "error",
        "correction": "correction",
        "reflection": "reflection",
        "rule": "rule",
    }

    for exp_type in type_colors:
        experiences = store.query_by_type(exp_type, limit=50)
        for exp in experiences:
            nodes.append({
                "id": f"{exp_type}:{exp.id}",
                "type": type_colors[exp_type],
                "label": exp.trigger[:60],
                "confidence": exp.confidence,
                "use_count": exp.use_count,
            })

            modules = exp.context.get("modules", [])
            for mod in modules:
                mod_id = f"module:{mod}"
                if not any(n["id"] == mod_id for n in nodes):
                    nodes.append({
                        "id": mod_id,
                        "type": "module",
                        "label": mod,
                    })
                edges.append({
                    "source": f"{exp_type}:{exp.id}",
                    "target": mod_id,
                    "type": "USES_MODULE",
                })

    return {"nodes": nodes, "edges": edges}


@router.get("/knowledge/stats")
async def knowledge_stats(_: Any = Depends(verify_api_key)) -> dict[str, Any]:
    store = _get_store()
    try:
        return await asyncio.to_thread(_build_stats, store)
    except Exception:
        logger.warning("knowledge_stats_failed", exc_info=True)
        return {"stats": None, "recent_errors": []}


@router.get("/knowledge/graph")
async def knowledge_graph_data(_: Any = Depends(verify_api_key)) -> dict[str, Any]:
    store = _get_store()
    try:
        return await asyncio.to_thread(_build_graph, store)
    except Exception:
        logger.warning("knowledge_graph_data_failed", exc_info=True)
        return {"nodes": [], "edges": []}


@router.get("/knowledge/workspace-memory")
async def get_workspace_memory(_: Any = Depends(verify_api_key)) -> dict[str, str]:
    try:
        from ansible_forge.knowledge.workspace_memory import WorkspaceMemory
        mem = WorkspaceMemory("default")
        return {"content": mem.read()}
    except Exception:
        logger.debug("workspace_memory_read_failed", exc_info=True)
        return {"content": ""}
