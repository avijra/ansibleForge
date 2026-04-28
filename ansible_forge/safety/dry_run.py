"""Execute playbooks in check+diff mode for safe previewing."""

from __future__ import annotations

from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import ToolResult
from ansible_forge.tools.executor import Executor

logger = get_logger(__name__)


class DryRunner:
    """Wraps the Executor tool forcing check mode for safe previewing."""

    def __init__(self) -> None:
        self._executor = Executor()

    async def run(
        self,
        workspace_path: str,
        playbook: str,
        inventory: str = "",
        extra_vars: dict[str, Any] | None = None,
        limit: str = "",
        tags: str = "",
    ) -> ToolResult:
        logger.info("dry_run_starting", playbook=playbook, workspace=workspace_path)
        return await self._executor.execute(
            workspace_path=workspace_path,
            playbook=playbook,
            mode="check",
            inventory=inventory,
            extra_vars=extra_vars,
            limit=limit,
            tags=tags,
            verbosity=1,
        )
