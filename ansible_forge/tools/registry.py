"""Auto-discovery tool registry — discovers and manages all available tools."""

from __future__ import annotations

from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool

logger = get_logger(__name__)


class ToolRegistry:
    """Central registry for all Ansible tools.

    Tools register themselves; the registry exposes them as OpenAI-format
    function definitions for the LLM and dispatches execution by name.
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            logger.warning("tool_already_registered", name=tool.name)
        self._tools[tool.name] = tool
        logger.debug("tool_registered", name=tool.name)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def to_openai_tools(self) -> list[dict[str, Any]]:
        """Return all tools as OpenAI-compatible function definitions."""
        return [tool.to_openai_tool() for tool in self._tools.values()]

    async def execute(self, name: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(name)
        if tool is None:
            from ansible_forge.tools.base import ToolResult

            return ToolResult.fail(f"Unknown tool: {name}")
        logger.info("tool_executing", tool=name, args=list(arguments.keys()))
        return await tool.execute(**arguments)


def create_default_registry() -> ToolRegistry:
    """Instantiate a registry with all built-in tools."""
    from ansible_forge.tools.doc_searcher import DocSearcher
    from ansible_forge.tools.executor import Executor
    from ansible_forge.tools.facts_collector import FactsCollector
    from ansible_forge.tools.file_writer import FileWriter
    from ansible_forge.tools.galaxy_manager import GalaxyManager
    from ansible_forge.tools.inventory_manager import InventoryManager
    from ansible_forge.tools.lint_runner import LintRunner
    from ansible_forge.tools.molecule_runner import MoleculeRunner
    from ansible_forge.tools.playbook_generator import PlaybookGenerator
    from ansible_forge.tools.role_scaffolder import RoleScaffolder
    from ansible_forge.tools.secret_requester import SecretRequester
    from ansible_forge.tools.vault_manager import VaultManager
    from ansible_forge.tools.web_searcher import WebSearcher

    registry = ToolRegistry()
    for tool_cls in (
        PlaybookGenerator,
        RoleScaffolder,
        InventoryManager,
        VaultManager,
        LintRunner,
        MoleculeRunner,
        GalaxyManager,
        Executor,
        FactsCollector,
        DocSearcher,
        WebSearcher,
        FileWriter,
        SecretRequester,
    ):
        registry.register(tool_cls())
    return registry
