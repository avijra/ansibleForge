"""Direct execution endpoints (bypass chat, provide playbook directly)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.api.schemas.requests import ExecuteRequest
from ansible_forge.api.schemas.responses import ExecuteResponse
from ansible_forge.tools.executor import Executor
from ansible_forge.tools.playbook_generator import PlaybookGenerator
from ansible_forge.workspace.manager import WorkspaceManager
from ansible_forge.workspace.project_layout import ensure_ansible_cfg

router = APIRouter()


@router.post("/execute", response_model=ExecuteResponse)
async def execute_playbook(
    request: ExecuteRequest,
    _: Any = Depends(verify_api_key),
) -> ExecuteResponse:
    """Execute a playbook directly without going through the chat agent.

    Change-making (`mode=apply`) requires an explicit ``confirm_apply`` flag so
    this non-interactive path cannot make infrastructure changes unattended.
    Previews (``mode=check``) are always allowed.
    """
    if request.mode == "apply" and not request.confirm_apply:
        return ExecuteResponse(
            status="error",
            output=(
                "Refusing to apply without confirmation. Re-run with "
                "confirm_apply=true to make changes, or use mode=check to preview. "
                "For guided execution with approval and verification, use the chat agent."
            ),
        )

    ws_mgr = WorkspaceManager()
    ws = ws_mgr.create()

    try:
        gen = PlaybookGenerator()
        gen_result = await gen.execute(
            playbook_name="playbook.yml",
            content=request.playbook_content,
            workspace_path=str(ws.path),
        )
        if gen_result.error:
            return ExecuteResponse(status="error", output=gen_result.error)

        if request.inventory_content:
            from ansible_forge.tools.inventory_manager import InventoryManager

            inv = InventoryManager()
            await inv.execute(
                action="create",
                workspace_path=str(ws.path),
                content=request.inventory_content,
            )

        ensure_ansible_cfg(ws.path)

        executor = Executor()
        result = await executor.execute(
            workspace_path=str(ws.path),
            playbook="playbook.yml",
            mode=request.mode,
            inventory="hosts.yml" if request.inventory_content else "",
            extra_vars=request.extra_vars,
        )

        return ExecuteResponse(
            status=result.status.value,
            output=result.output,
            data=result.data,
        )
    finally:
        ws_mgr.destroy(ws.session_id)
