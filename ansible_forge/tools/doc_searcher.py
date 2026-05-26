"""Search ansible-doc for module documentation, examples, and parameters."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class DocSearcher(BaseTool):
    @property
    def name(self) -> str:
        return "search_docs"

    @property
    def description(self) -> str:
        return (
            "Search Ansible module documentation using ansible-doc. "
            "Can list available modules matching a filter, show full documentation "
            "for a specific module, or show usage examples."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "show", "snippet"],
                    "description": "'list' to search modules, 'show' for full docs, 'snippet' for examples",
                },
                "module_name": {
                    "type": "string",
                    "description": "Module FQCN or search filter (e.g. 'ansible.builtin.apt', 'docker')",
                },
                "doc_type": {
                    "type": "string",
                    "enum": ["module", "role", "collection", "lookup", "filter"],
                    "description": "Type of plugin to search (default: module)",
                },
            },
            "required": ["action", "module_name"],
        }

    async def execute(
        self,
        action: str = "",
        module_name: str = "",
        doc_type: str = "module",
        **kwargs: Any,
    ) -> ToolResult:
        if not action or not module_name:
            return ToolResult.fail("action and module_name are required")

        if action == "list":
            return await self._list_modules(module_name, doc_type)
        if action == "show":
            return await self._show_doc(module_name, doc_type)
        if action == "snippet":
            return await self._show_snippet(module_name, doc_type)
        return ToolResult.fail(f"Unknown action: {action}")

    async def _list_modules(self, filter_str: str, doc_type: str) -> ToolResult:
        rc, stdout, stderr = await self._run_ansible_doc(
            "--list", "--json", f"--type={doc_type}"
        )
        if rc != 0:
            return ToolResult.fail(f"ansible-doc list failed: {stderr}")

        try:
            all_modules = json.loads(stdout)
        except json.JSONDecodeError:
            return ToolResult.fail("Failed to parse ansible-doc JSON output")

        matched = {
            k: v for k, v in all_modules.items() if filter_str.lower() in k.lower()
        }

        return ToolResult.ok(
            output=f"Found {len(matched)} modules matching '{filter_str}'",
            modules=dict(list(matched.items())[:50]),
            total_matches=len(matched),
        )

    async def _show_doc(self, module_name: str, doc_type: str) -> ToolResult:
        rc, stdout, stderr = await self._run_ansible_doc(
            module_name, "--json", f"--type={doc_type}"
        )
        if rc != 0:
            return ToolResult.fail(f"ansible-doc failed for '{module_name}': {stderr}")

        try:
            docs = json.loads(stdout)
        except json.JSONDecodeError:
            return ToolResult.ok(output=stdout)

        return ToolResult.ok(output=json.dumps(docs, indent=2)[:8000], docs=docs)

    async def _show_snippet(self, module_name: str, doc_type: str) -> ToolResult:
        rc, stdout, stderr = await self._run_ansible_doc(
            module_name, "--snippet", f"--type={doc_type}"
        )
        if rc != 0:
            return ToolResult.fail(f"ansible-doc snippet failed for '{module_name}': {stderr}")
        return ToolResult.ok(output=stdout)

    @staticmethod
    async def _run_ansible_doc(*args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "ansible-doc",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=60)
        except asyncio.CancelledError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            raise
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return (1, "", "ansible-doc timed out after 60s")
        return (
            proc.returncode or 0,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
        )
