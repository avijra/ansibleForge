"""Search, install, and manage Ansible Galaxy collections and roles."""

from __future__ import annotations

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
                    "enum": ["search", "install", "list", "install_role", "list_roles", "create_requirements", "install_requirements", "discover_roles"],
                    "description": "Galaxy operation to perform. Use 'discover_roles' to scan workspace/roles/ and list installed Galaxy roles with descriptions.",
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
            return await self._install(collection_name, version, workspace_path)
        if action == "list":
            return await self._list_installed()
        if action == "install_role":
            return await self._install_role(collection_name, version)
        if action == "list_roles":
            return await self._list_roles()
        if action == "create_requirements":
            return self._create_requirements(requirements or [], workspace_path)
        if action == "install_requirements":
            return await self._install_requirements(workspace_path)
        if action == "discover_roles":
            return await self._discover_roles(workspace_path)
        return ToolResult.fail(f"Unknown action: {action}")

    _GALAXY_API = "https://galaxy.ansible.com/api/v3/plugin/ansible/search/collection-versions/"

    async def _search(self, query: str) -> ToolResult:
        if not query:
            return ToolResult.fail("collection_name is required for search")

        rc, stdout, stderr = await self._run_galaxy(
            "collection", "list", "--format=json"
        )

        local_results: list[dict[str, str]] = []
        if rc == 0:
            try:
                data = json.loads(stdout)
                for path_collections in data.values():
                    for name, info in path_collections.items():
                        if query.lower() in name.lower():
                            local_results.append({
                                "name": name,
                                "version": info.get("version", "unknown"),
                                "source": "installed",
                            })
            except (json.JSONDecodeError, AttributeError):
                logger.debug("galaxy_list_parse_failed", exc_info=True)

        online_results = await self._search_galaxy_api(query)

        seen = {r["name"] for r in local_results}
        merged = list(local_results)
        for r in online_results:
            if r["name"] not in seen:
                merged.append(r)
                seen.add(r["name"])

        hint = ""
        installable = [r for r in merged if r.get("source") == "galaxy"]
        if installable:
            names = ", ".join(r["name"] for r in installable[:3])
            hint = (
                f" To install: `manage_galaxy action=install collection_name={installable[0]['name']}`."
                f" Available online: {names}."
            )

        return ToolResult.ok(
            output=f"Found {len(local_results)} installed, {len(online_results)} on Galaxy matching '{query}'.{hint}",
            collections=merged,
        )

    async def _search_galaxy_api(self, query: str) -> list[dict[str, str]]:
        import httpx

        results: list[dict[str, str]] = []
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
                resp = await client.get(
                    self._GALAXY_API,
                    params={"keywords": query, "limit": 10, "is_highest": True},
                )
                if resp.status_code != 200:
                    logger.debug("galaxy_api_non_200", status=resp.status_code)
                    return results
                data = resp.json().get("data", [])
                for item in data:
                    fqcn = f"{item.get('namespace', '')}.{item.get('name', '')}"
                    if "." not in fqcn or not fqcn.strip("."):
                        continue
                    results.append({
                        "name": fqcn,
                        "version": item.get("highest_version", {}).get("version", "latest"),
                        "description": (item.get("description") or "")[:120],
                        "source": "galaxy",
                    })
        except Exception:
            logger.debug("galaxy_api_search_failed", exc_info=True)
        return results

    async def _install(
        self, collection_name: str, version: str, workspace_path: str = ""
    ) -> ToolResult:
        if not collection_name:
            return ToolResult.fail("collection_name is required for install")

        target = f"{collection_name}:{version}" if version else collection_name
        rc, stdout, stderr = await self._run_galaxy(
            "collection", "install", target, "--force", workspace=workspace_path
        )

        if rc != 0:
            return ToolResult.fail(f"Package install failed: {stderr or stdout}")

        from ansible_forge.tools.ee_runtime import is_ee_enabled

        extra = ""
        if not is_ee_enabled():
            from ansible_forge.dep_manager import ensure_collection_deps

            _dep_ok, dep_msg = await ensure_collection_deps(collection_name)
            extra = f"\n{dep_msg}" if dep_msg else ""

        return ToolResult.ok(
            output=f"Package '{target}' installed successfully.{extra}",
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

    async def _install_requirements(self, workspace_path: str) -> ToolResult:
        if not workspace_path:
            return ToolResult.fail("workspace_path is required for install_requirements")

        from pathlib import Path

        req_path = Path(workspace_path) / "requirements.yml"
        if not req_path.exists():
            return ToolResult.fail(f"requirements.yml not found at {req_path}")

        rc, stdout, stderr = await self._run_galaxy(
            "collection", "install", "-r", str(req_path), "--force",
            timeout=600, workspace=workspace_path,
        )
        role_msg = ""
        rc2, stdout2, stderr2 = await self._run_galaxy(
            "role", "install", "-r", str(req_path), "--force",
            timeout=600, workspace=workspace_path,
        )
        if rc2 == 0 and stdout2.strip():
            role_msg = f" Roles: {stdout2.strip()[-500:]}"

        if rc != 0:
            return ToolResult.fail(
                f"Failed to install from requirements.yml: {stderr or stdout}"
            )

        # Auto-install Python SDK dependencies for collections in requirements.yml.
        # In EE mode the container ships these SDKs; host installs are skipped.
        from ansible_forge.tools.ee_runtime import is_ee_enabled

        dep_msgs: list[str] = []
        if not is_ee_enabled():
            try:
                import yaml as _yaml

                req_data = _yaml.safe_load(req_path.read_text(encoding="utf-8"))
                collections_list = req_data.get("collections", []) if isinstance(req_data, dict) else []
                from ansible_forge.dep_manager import ensure_collection_deps

                for entry in collections_list:
                    name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
                    if name:
                        _, msg = await ensure_collection_deps(name)
                        if msg:
                            dep_msgs.append(msg)
            except Exception:
                pass  # Don't fail the install if dep resolution has issues

        dep_extra = (" " + "; ".join(dep_msgs)) if dep_msgs else ""
        return ToolResult.ok(
            output=f"All requirements installed from {req_path}.{role_msg}{dep_extra}",
        )

    async def _discover_roles(self, workspace_path: str) -> ToolResult:
        from pathlib import Path

        import yaml as _yaml

        roles: list[dict[str, Any]] = []

        if workspace_path:
            roles_dir = Path(workspace_path) / "roles"
            if roles_dir.is_dir():
                for entry in sorted(roles_dir.iterdir()):
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                    role_info: dict[str, Any] = {"name": entry.name, "source": "workspace"}
                    meta_file = entry / "meta" / "main.yml"
                    if not meta_file.exists():
                        meta_file = entry / "meta" / "main.yaml"
                    if meta_file.exists():
                        try:
                            meta = _yaml.safe_load(meta_file.read_text(encoding="utf-8"))
                            if isinstance(meta, dict):
                                gi = meta.get("galaxy_info", {})
                                if isinstance(gi, dict):
                                    role_info["description"] = gi.get("description", "")
                                    role_info["author"] = gi.get("author", "")
                                    role_info["platforms"] = [
                                        p.get("name", "") for p in gi.get("platforms", [])
                                        if isinstance(p, dict)
                                    ][:5]
                                deps = meta.get("dependencies", [])
                                if deps:
                                    role_info["dependencies"] = [
                                        str(d) for d in deps[:10]
                                    ]
                        except Exception:
                            pass
                    tasks_main = entry / "tasks" / "main.yml"
                    if not tasks_main.exists():
                        tasks_main = entry / "tasks" / "main.yaml"
                    role_info["has_tasks"] = tasks_main.exists()
                    roles.append(role_info)

        galaxy_roles = await self._list_roles()
        galaxy_list: list[dict[str, str]] = []
        if galaxy_roles.data.get("roles"):
            galaxy_list = galaxy_roles.data["roles"]

        return ToolResult.ok(
            output=(
                f"Found {len(roles)} workspace role(s) and "
                f"{len(galaxy_list)} installed Galaxy role(s). "
                f"Check existing roles before creating new ones."
            ),
            workspace_roles=roles,
            galaxy_roles=galaxy_list,
        )

    @staticmethod
    def _default_collections_path() -> str:
        from pathlib import Path

        home = Path.home()
        path = home / ".ansible" / "collections"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    @staticmethod
    async def _run_galaxy(
        *args: str, timeout: int = 300, workspace: str = "",
    ) -> tuple[int, str, str]:
        import os

        from ansible_forge.tools.ee_runtime import ee_exec, is_ee_enabled

        env: dict[str, str] = {}
        ssl_cert = os.environ.get("SSL_CERT_FILE", "")
        if ssl_cert:
            env["SSL_CERT_FILE"] = ssl_cert
            env["REQUESTS_CA_BUNDLE"] = os.environ.get("REQUESTS_CA_BUNDLE", ssl_cert)

        from pathlib import Path

        ws_path = Path(workspace) if workspace else None
        cmd = ["ansible-galaxy", *args]
        if ws_path and is_ee_enabled():
            collections = ws_path / ".ansible" / "collections"
            collections.mkdir(parents=True, exist_ok=True)
            if "-p" not in args and "--collections-path" not in args:
                cmd.extend(["-p", str(collections)])
        return await ee_exec(
            cmd,
            env=env if env else None,
            timeout=timeout,
            ws=ws_path,
            cwd=ws_path,
        )

