"""Search, install, and manage Ansible Galaxy collections and roles."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class GalaxyManager(BaseTool):
    @property
    def name(self) -> str:
        return "manage_galaxy"

    @property
    def description(self) -> str:
        return (
            "Manage Ansible Galaxy collections and roles: search, install, list, "
            "or create a requirements.yml file. Supports both collections (FQCN) "
            "and roles (namespace.role_name)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["search", "install", "list", "install_role", "list_roles", "create_requirements"],
                    "description": "Galaxy operation to perform",
                },
                "collection_name": {
                    "type": "string",
                    "description": "Collection FQCN (e.g. 'community.general') or role name (e.g. 'geerlingguy.docker') for install/search",
                },
                "version": {
                    "type": "string",
                    "description": "Specific version to install (optional)",
                },
                "requirements": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "version": {"type": "string"},
                        },
                        "required": ["name"],
                    },
                    "description": "List of collections/roles for create_requirements",
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Workspace path (for create_requirements output)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        collection_name: str = "",
        version: str = "",
        requirements: list[dict[str, str]] | None = None,
        workspace_path: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not action:
            return ToolResult.fail("action is required")

        if action == "search":
            return await self._search(collection_name)
        if action == "install":
            return await self._install(collection_name, version)
        if action == "list":
            return await self._list_installed()
        if action == "install_role":
            return await self._install_role(collection_name, version)
        if action == "list_roles":
            return await self._list_roles()
        if action == "create_requirements":
            return self._create_requirements(requirements or [], workspace_path)
        return ToolResult.fail(f"Unknown action: {action}")

    async def _search(self, query: str) -> ToolResult:
        if not query:
            return ToolResult.fail("collection_name is required for search")

        rc, stdout, stderr = await self._run_galaxy(
            "collection", "list", "--format=json"
        )

        results: list[dict[str, str]] = []
        if rc == 0:
            try:
                data = json.loads(stdout)
                for path_collections in data.values():
                    for name, info in path_collections.items():
                        if query.lower() in name.lower():
                            results.append({
                                "name": name,
                                "version": info.get("version", "unknown"),
                            })
            except (json.JSONDecodeError, AttributeError):
                pass

        return ToolResult.ok(
            output=f"Found {len(results)} installed package(s) matching '{query}'.",
            collections=results,
        )

    async def _install(self, collection_name: str, version: str) -> ToolResult:
        if not collection_name:
            return ToolResult.fail("collection_name is required for install")

        target = f"{collection_name}:{version}" if version else collection_name
        rc, stdout, stderr = await self._run_galaxy(
            "collection", "install", target, "--force"
        )

        if rc != 0:
            return ToolResult.fail(f"Package install failed: {stderr or stdout}")

        return ToolResult.ok(
            output=f"Package '{target}' installed successfully.",
        )

    async def _list_installed(self) -> ToolResult:
        rc, stdout, stderr = await self._run_galaxy(
            "collection", "list", "--format=json",
            f"--collections-path={self._default_collections_path()}",
        )
        if rc != 0:
            # Retry without --collections-path for systems using only global paths
            rc, stdout, stderr = await self._run_galaxy(
                "collection", "list",
            )
            if rc != 0:
                return ToolResult.fail(f"Could not list installed packages: {stderr}")

        try:
            data = json.loads(stdout)
            collections: list[dict[str, str]] = []
            for path_collections in data.values():
                for name, info in path_collections.items():
                    collections.append({
                        "name": name,
                        "version": info.get("version", "unknown"),
                    })
            return ToolResult.ok(
                output=f"{len(collections)} package(s) installed.",
                collections=collections,
            )
        except (json.JSONDecodeError, AttributeError):
            return ToolResult.ok(output=stdout)

    async def _install_role(self, role_name: str, version: str) -> ToolResult:
        if not role_name:
            return ToolResult.fail("collection_name (role name) is required for install_role")

        target = f"{role_name},{version}" if version else role_name
        rc, stdout, stderr = await self._run_galaxy("role", "install", target, "--force")

        if rc != 0:
            return ToolResult.fail(f"Role install failed: {stderr or stdout}")
        return ToolResult.ok(output=f"Role '{target}' installed successfully.")

    async def _list_roles(self) -> ToolResult:
        rc, stdout, stderr = await self._run_galaxy("role", "list")
        if rc != 0:
            return ToolResult.fail(f"Could not list installed roles: {stderr}")

        roles: list[dict[str, str]] = []
        for line in stdout.splitlines():
            line = line.strip()
            if line.startswith("-") and "," in line:
                parts = line.lstrip("- ").split(",", 1)
                roles.append({
                    "name": parts[0].strip(),
                    "version": parts[1].strip() if len(parts) > 1 else "unknown",
                })
        return ToolResult.ok(
            output=f"{len(roles)} role(s) installed.",
            roles=roles,
        )

    @staticmethod
    def _create_requirements(
        requirements: list[dict[str, str]], workspace_path: str
    ) -> ToolResult:
        if not requirements or not workspace_path:
            return ToolResult.fail("requirements list and workspace_path are needed")

        from pathlib import Path

        import yaml

        content: dict[str, list[dict[str, str]]] = {"collections": [], "roles": []}
        for req in requirements:
            entry: dict[str, str] = {"name": req["name"]}
            if req.get("version"):
                entry["version"] = req["version"]
            if req.get("type") == "role":
                content["roles"].append(entry)
            else:
                content["collections"].append(entry)
        if not content["roles"]:
            del content["roles"]
        if not content["collections"]:
            del content["collections"]

        out_path = Path(workspace_path) / "requirements.yml"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            yaml.dump(content, default_flow_style=False, sort_keys=False), encoding="utf-8"
        )
        return ToolResult.ok(
            output=f"requirements.yml created at {out_path}",
            path=str(out_path),
        )

    @staticmethod
    def _default_collections_path() -> str:
        from pathlib import Path

        home = Path.home()
        path = home / ".ansible" / "collections"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    @staticmethod
    async def _run_galaxy(*args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "ansible-galaxy",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
        )
