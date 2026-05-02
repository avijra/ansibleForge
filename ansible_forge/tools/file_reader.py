"""Read files from the workspace or anywhere on the host filesystem."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

MAX_READ_BYTES = 512_000


class FileReader(BaseTool):

    @property
    def name(self) -> str:
        return "read_file"

    @property
    def description(self) -> str:
        return (
            "Read the contents of a file from the workspace or the local filesystem. "
            "Use this to inspect playbooks, templates, configuration files, inventory, "
            "variable files, or any text file you need to review before making changes. "
            "For reading files on remote hosts, use run_adhoc with the shell module instead."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Path to the file. Can be a relative path within the workspace "
                        "(e.g. 'inventory/hosts.yml', 'roles/myrole/tasks/main.yml') "
                        "or an absolute path on the host filesystem."
                    ),
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory (used to resolve relative paths).",
                },
            },
            "required": ["file_path"],
        }

    async def execute(
        self,
        file_path: str = "",
        workspace_path: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not file_path:
            return ToolResult.fail("file_path is required")

        path = Path(file_path)
        if not path.is_absolute() and workspace_path:
            path = Path(workspace_path) / file_path

        path = path.resolve()

        if not path.exists():
            return ToolResult.fail(f"File not found: {path}")
        if not path.is_file():
            if path.is_dir():
                entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
                listing = "\n".join(entries[:200])
                return ToolResult.ok(
                    output=f"Directory listing for {path} ({len(entries)} entries):\n{listing}",
                    is_directory=True,
                    entry_count=len(entries),
                )
            return ToolResult.fail(f"Not a regular file: {path}")

        try:
            size = path.stat().st_size
            if size > MAX_READ_BYTES:
                content = path.read_bytes()[:MAX_READ_BYTES].decode("utf-8", errors="replace")
                return ToolResult.ok(
                    output=content,
                    path=str(path),
                    size=size,
                    truncated=True,
                    truncated_at=MAX_READ_BYTES,
                )
            content = path.read_text(encoding="utf-8", errors="replace")
        except PermissionError:
            return ToolResult.fail(f"Permission denied: {path}")
        except Exception as exc:
            return ToolResult.fail(f"Failed to read {path}: {exc}")

        logger.info("file_read", path=str(path), size=len(content))

        return ToolResult.ok(
            output=content if content else "(empty file)",
            path=str(path),
            size=len(content),
        )
