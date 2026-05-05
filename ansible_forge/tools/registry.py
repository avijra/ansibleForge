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

    @property
    def tool_summaries(self) -> list[dict[str, str]]:
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

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
    from ansible_forge.tools.adhoc_runner import AdhocRunner
    from ansible_forge.tools.compliance_scanner import ComplianceScanner
    from ansible_forge.tools.config_comparator import ConfigComparator
    from ansible_forge.tools.connectivity_tester import ConnectivityTester
    from ansible_forge.tools.doc_searcher import DocSearcher
    from ansible_forge.tools.drift_detector import DriftDetector
    from ansible_forge.tools.executor import Executor
    from ansible_forge.tools.facts_collector import FactsCollector
    from ansible_forge.tools.file_reader import FileReader
    from ansible_forge.tools.file_writer import FileWriter
    from ansible_forge.tools.galaxy_manager import GalaxyManager
    from ansible_forge.tools.git_manager import GitManager
    from ansible_forge.tools.inventory_discovery import InventoryDiscoveryTool
    from ansible_forge.tools.inventory_manager import InventoryManager
    from ansible_forge.tools.lint_runner import LintRunner
    from ansible_forge.tools.local_exec import LocalExec
    from ansible_forge.tools.log_analyzer import LogAnalyzer
    from ansible_forge.tools.memory_tool import MemoryTool
    from ansible_forge.tools.molecule_runner import MoleculeRunner
    from ansible_forge.tools.playbook_generator import PlaybookGenerator
    from ansible_forge.tools.project_importer import ProjectImporter
    from ansible_forge.tools.role_scaffolder import RoleScaffolder
    from ansible_forge.tools.rollback_tool import RollbackTool
    from ansible_forge.tools.schedule_manager import ScheduleManager
    from ansible_forge.tools.secret_requester import SecretRequester
    from ansible_forge.tools.session_search import SessionSearchTool
    from ansible_forge.tools.template_renderer import TemplateRenderer
    from ansible_forge.tools.terraform_executor import TerraformExecutor
    from ansible_forge.tools.terraform_generator import TerraformGenerator
    from ansible_forge.tools.terraform_inventory import TerraformInventoryBridge
    from ansible_forge.tools.variable_inspector import VariableInspector
    from ansible_forge.tools.vault_manager import VaultManager
    from ansible_forge.tools.verifier import Verifier
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
        AdhocRunner,
        FactsCollector,
        ConnectivityTester,
        DocSearcher,
        WebSearcher,
        FileReader,
        FileWriter,
        SecretRequester,
        RollbackTool,
        Verifier,
        InventoryDiscoveryTool,
        TemplateRenderer,
        GitManager,
        DriftDetector,
        ComplianceScanner,
        VariableInspector,
        ConfigComparator,
        ScheduleManager,
        ProjectImporter,
        LocalExec,
        LogAnalyzer,
        TerraformGenerator,
        TerraformExecutor,
        TerraformInventoryBridge,
        MemoryTool,
        SessionSearchTool,
    ):
        registry.register(tool_cls())

    try:
        from ansible_forge.plugins.loader import load_plugins
        loaded = load_plugins(registry)
        if loaded:
            logger.info("plugins_loaded", count=len(loaded), names=[p["name"] for p in loaded])
    except Exception:
        logger.debug("plugin_loading_failed", exc_info=True)

    return registry
