"""REST lint endpoint — runs ansible-lint on a session workspace."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.tools.lint_runner import LintRunner
from ansible_forge.workspace.manager import WorkspaceManager

router = APIRouter()


class LintRequest(BaseModel):
    file: str | None = Field(None, description="Optional relative file path to lint")
    profile: str = Field("moderate", description="Lint profile")


@router.post("/lint/{session_id}")
async def run_lint(
    session_id: str,
    body: LintRequest | None = None,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    ws_mgr = WorkspaceManager()
    ws = ws_mgr.get(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    target = str(ws.project_dir)
    profile = "moderate"

    if body:
        profile = body.profile or "moderate"
        if body.file:
            candidate = (ws.path / body.file).resolve()
            if not str(candidate).startswith(str(ws.path.resolve())):
                raise HTTPException(status_code=400, detail="Path traversal not allowed")
            if candidate.is_file():
                target = str(candidate)

    runner = LintRunner()
    result = await runner.execute(target=target, profile=profile)

    violations = result.data.get("violations", []) if result.data else []

    return {
        "session_id": session_id,
        "violation_count": len(violations),
        "violations": violations,
        "profile": profile,
        "output": result.output,
    }


@router.get("/lint/{session_id}")
async def get_lint(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    """GET variant — runs lint with defaults for convenience."""
    ws_mgr = WorkspaceManager()
    ws = ws_mgr.get(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    runner = LintRunner()
    result = await runner.execute(target=str(ws.project_dir), profile="moderate")
    violations = result.data.get("violations", []) if result.data else []

    return {
        "session_id": session_id,
        "violation_count": len(violations),
        "violations": violations,
        "profile": "moderate",
        "output": result.output,
    }
