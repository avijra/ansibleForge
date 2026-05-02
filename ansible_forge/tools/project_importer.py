"""Import existing Ansible projects from local directories or Git repos into a workspace."""

from __future__ import annotations

import asyncio
import functools
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_ANSIBLE_MARKERS = (
    "ansible.cfg", "site.yml", "playbook.yml", "requirements.yml",
    "roles", "inventory", "group_vars", "host_vars",
)

_PLAYBOOK_EXTENSIONS = (".yml", ".yaml")


class ProjectImporter(BaseTool):
    @property
    def name(self) -> str:
        return "import_project"

    @property
    def description(self) -> str:
        return (
            "Import an existing Ansible project from a local directory or Git repository "
            "into the current workspace. Detects project structure (playbooks, roles, "
            "inventory, group_vars, host_vars, templates) and copies them into the "
            "workspace project directory. Returns a summary of discovered components."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory to import into",
                },
                "source_path": {
                    "type": "string",
                    "description": (
                        "Absolute path to a local directory containing the Ansible project. "
                        "Provide this OR git_url, not both."
                    ),
                },
                "git_url": {
                    "type": "string",
                    "description": (
                        "Git repository URL to clone (e.g. 'https://github.com/org/ansible-project.git'). "
                        "Provide this OR source_path, not both."
                    ),
                },
                "git_branch": {
                    "type": "string",
                    "description": "Git branch to checkout (default: default branch)",
                },
                "subdirectory": {
                    "type": "string",
                    "description": "Subdirectory within the source to import (if project isn't at root)",
                },
            },
            "required": ["workspace_path"],
        }

    async def execute(
        self,
        workspace_path: str = "",
        source_path: str = "",
        git_url: str = "",
        git_branch: str = "",
        subdirectory: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path:
            return ToolResult.fail("workspace_path is required")
        if not source_path and not git_url:
            return ToolResult.fail("Provide either source_path or git_url")

        ws = Path(workspace_path)
        project_dir = ws
        project_dir.mkdir(parents=True, exist_ok=True)

        if git_url:
            clone_result = await self._clone_repo(git_url, git_branch, ws)
            if clone_result.status != "success":
                return clone_result
            source_path = str(ws / ".tuyere" / "_import_clone")

        src = Path(source_path)
        if subdirectory:
            src = src / subdirectory

        if not src.exists():
            return ToolResult.fail(f"Source path not found: {src}")

        analysis = self._analyze_project(src)
        imported = self._copy_project(src, project_dir, ws)

        clone_dir = ws / ".tuyere" / "_import_clone"
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)

        return ToolResult.ok(
            output=(
                f"Imported project from {'git' if git_url else 'local'}: "
                f"{imported['playbooks']} playbook(s), {imported['roles']} role(s), "
                f"{imported['inventory_files']} inventory file(s), "
                f"{imported['template_files']} template(s), "
                f"{imported['total_files']} total file(s)"
            ),
            analysis=analysis,
            imported=imported,
            source=git_url or source_path,
        )

    async def _clone_repo(self, url: str, branch: str, ws: Path) -> ToolResult:
        clone_dir = ws / ".tuyere" / "_import_clone"
        if clone_dir.exists():
            shutil.rmtree(clone_dir, ignore_errors=True)

        cmd = ["git", "clone", "--depth", "1"]
        if branch:
            cmd.extend(["--branch", branch])
        cmd.extend([url, str(clone_dir)])

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    functools.partial(
                        subprocess.run, cmd,
                        capture_output=True, text=True, timeout=120,
                    ),
                ),
                timeout=130,
            )
            if result.returncode != 0:
                return ToolResult.fail(f"Git clone failed: {result.stderr.strip()}")
        except (TimeoutError, subprocess.TimeoutExpired):
            return ToolResult.fail("Git clone timed out after 2 minutes")

        return ToolResult.ok(output="Repository cloned")

    def _analyze_project(self, src: Path) -> dict[str, Any]:
        analysis: dict[str, Any] = {
            "has_ansible_cfg": (src / "ansible.cfg").exists(),
            "has_requirements": (src / "requirements.yml").exists(),
            "playbooks": [],
            "roles": [],
            "inventory_dirs": [],
            "group_vars_dirs": [],
            "host_vars_dirs": [],
            "collections_required": [],
        }

        for f in src.iterdir():
            if f.suffix in _PLAYBOOK_EXTENSIONS and f.is_file():
                if self._is_playbook(f):
                    analysis["playbooks"].append(f.name)

        roles_dir = src / "roles"
        if roles_dir.exists():
            analysis["roles"] = [d.name for d in roles_dir.iterdir() if d.is_dir()]

        for inv_name in ("inventory", "inventories"):
            inv_dir = src / inv_name
            if inv_dir.exists():
                analysis["inventory_dirs"].append(inv_name)

        if (src / "group_vars").exists():
            analysis["group_vars_dirs"].append("group_vars")
        if (src / "host_vars").exists():
            analysis["host_vars_dirs"].append("host_vars")

        req_file = src / "requirements.yml"
        if req_file.exists():
            try:
                data = yaml.safe_load(req_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    collections = data.get("collections", [])
                    analysis["collections_required"] = [
                        c.get("name", c) if isinstance(c, dict) else str(c)
                        for c in collections
                    ]
                elif isinstance(data, list):
                    analysis["collections_required"] = [
                        c.get("name", c) if isinstance(c, dict) else str(c)
                        for c in data
                    ]
            except yaml.YAMLError:
                pass

        return analysis

    def _is_playbook(self, path: Path) -> bool:
        try:
            content = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(content, list) and content:
                first = content[0]
                return isinstance(first, dict) and any(
                    k in first for k in ("hosts", "tasks", "roles", "import_playbook", "include")
                )
        except (yaml.YAMLError, OSError):
            pass
        return False

    def _copy_project(self, src: Path, project_dir: Path, ws: Path) -> dict[str, int]:
        stats = {
            "playbooks": 0,
            "roles": 0,
            "inventory_files": 0,
            "template_files": 0,
            "total_files": 0,
        }

        skip_dirs = {".git", ".github", "__pycache__", ".tox", ".venv", "node_modules"}

        for item in src.rglob("*"):
            if any(p in item.parts for p in skip_dirs):
                continue
            if not item.is_file():
                continue

            rel = item.relative_to(src)
            dest = project_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            stats["total_files"] += 1

            if item.suffix in _PLAYBOOK_EXTENSIONS and self._is_playbook(item):
                stats["playbooks"] += 1
            if item.suffix == ".j2":
                stats["template_files"] += 1

            parts_set = set(rel.parts)
            if "inventory" in parts_set or "inventories" in parts_set:
                inv_dest = ws / "inventory" / rel.name
                inv_dest.parent.mkdir(parents=True, exist_ok=True)
                if not inv_dest.exists():
                    shutil.copy2(item, inv_dest)
                    stats["inventory_files"] += 1

        roles_dir = src / "roles"
        if roles_dir.exists():
            stats["roles"] = sum(1 for d in roles_dir.iterdir() if d.is_dir())

        return stats
