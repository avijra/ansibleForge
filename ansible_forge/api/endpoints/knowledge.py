"""Knowledge graph API endpoints for stats and graph data."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ansible_forge.config import get_settings
from ansible_forge.knowledge.graph import KnowledgeGraph
from ansible_forge.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _get_global_graph() -> KnowledgeGraph | None:
    settings = get_settings()
    if not settings.knowledge_enabled:
        return None
    global_path = settings.knowledge_dir / "global.kuzu"
    return KnowledgeGraph(global_path)


@router.get("/knowledge/stats")
async def knowledge_stats() -> dict[str, Any]:
    graph = _get_global_graph()
    if graph is None:
        return {"stats": None, "recent_errors": []}

    try:
        stats = {
            "hosts": graph.node_count("Host"),
            "modules": graph.node_count("Module"),
            "error_patterns": graph.node_count("ErrorPattern"),
            "resolutions": graph.node_count("Resolution"),
            "executions": graph.node_count("Execution"),
        }

        raw_errors = graph.query_recent_errors(limit=10)
        recent_errors = []
        for row in raw_errors:
            recent_errors.append({
                "pattern": row[0] or "",
                "module": row[1] or "",
                "os_family": row[2] or "",
                "resolution": row[3] or None,
                "resolved": bool(row[4]) if len(row) > 4 else False,
                "count": 1,
            })

        return {"stats": stats, "recent_errors": recent_errors}
    except Exception:
        logger.warning("knowledge_stats_failed", exc_info=True)
        return {"stats": None, "recent_errors": []}


@router.get("/knowledge/graph")
async def knowledge_graph_data() -> dict[str, Any]:
    graph = _get_global_graph()
    if graph is None:
        return {"nodes": [], "edges": []}

    try:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        for row in graph.execute("MATCH (h:Host) RETURN h.hostname, h.distribution, h.os_family"):
            nodes.append({
                "id": f"host:{row[0]}",
                "type": "host",
                "label": row[0],
                "distribution": row[1] or "",
                "os_family": row[2] or "",
            })

        for row in graph.execute("MATCH (m:Module) RETURN m.fqcn, m.doc_summary"):
            nodes.append({
                "id": f"module:{row[0]}",
                "type": "module",
                "label": row[0],
                "doc_summary": row[1] or "",
            })

        for row in graph.execute(
            "MATCH (e:ErrorPattern) RETURN e.message_hash, e.message_template, e.module"
        ):
            nodes.append({
                "id": f"error:{row[0]}",
                "type": "error",
                "label": (row[1] or "")[:60],
                "module": row[2] or "",
            })

        for row in graph.execute(
            "MATCH (r:Resolution) RETURN r.resolution_id, r.descr, r.success"
        ):
            nodes.append({
                "id": f"resolution:{row[0]}",
                "type": "resolution",
                "label": (row[1] or "")[:60],
                "success": bool(row[2]),
            })

        for row in graph.execute(
            "MATCH (h:Host)-[r:RAN_TASK]->(t:Task) "
            "RETURN h.hostname, t.task_id, r.outcome LIMIT 200"
        ):
            edges.append({
                "source": f"host:{row[0]}",
                "target": f"task:{row[1]}",
                "type": "RAN_TASK",
                "outcome": row[2] or "",
            })

        for row in graph.execute(
            "MATCH (e:ErrorPattern)-[:OCCURRED_ON]->(h:Host) "
            "RETURN e.message_hash, h.hostname"
        ):
            edges.append({
                "source": f"error:{row[0]}",
                "target": f"host:{row[1]}",
                "type": "OCCURRED_ON",
            })

        for row in graph.execute(
            "MATCH (r:Resolution)-[:RESOLVES]->(e:ErrorPattern) "
            "RETURN r.resolution_id, e.message_hash"
        ):
            edges.append({
                "source": f"resolution:{row[0]}",
                "target": f"error:{row[1]}",
                "type": "RESOLVES",
            })

        return {"nodes": nodes, "edges": edges}
    except Exception:
        logger.warning("knowledge_graph_data_failed", exc_info=True)
        return {"nodes": [], "edges": []}
