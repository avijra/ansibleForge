"""Encrypt and decrypt secrets using ansible-vault."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class VaultManager(BaseTool):
    @property
    def name(self) -> str:
        return "manage_vault"

    @property
    def description(self) -> str:
        return (
            "Encrypt or decrypt files and strings using ansible-vault. "
            "Can encrypt a file in-place, decrypt a file, encrypt a string value, "
            "or create an encrypted variable file."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["encrypt_file", "decrypt_file", "encrypt_string", "create_encrypted"],
                    "description": "Vault operation to perform",
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory",
                },
                "file_path": {
                    "type": "string",
                    "description": "Relative path to the file within the workspace (for file operations)",
                },
                "vault_password": {
                    "type": "string",
                    "description": "Vault password to use for encryption/decryption",
                },
                "content": {
                    "type": "string",
                    "description": "String content to encrypt (for encrypt_string/create_encrypted)",
                },
                "variable_name": {
                    "type": "string",
                    "description": "Variable name for encrypt_string output",
                },
            },
            "required": ["action", "workspace_path", "vault_password"],
        }

    async def execute(
        self,
        action: str = "",
        workspace_path: str = "",
        file_path: str = "",
        vault_password: str = "",
        content: str = "",
        variable_name: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not action or not workspace_path or not vault_password:
            return ToolResult.fail("action, workspace_path, and vault_password are required")

        pw_file = self._write_password_file(vault_password)

        try:
            if action == "encrypt_file":
                return await self._encrypt_file(workspace_path, file_path, pw_file)
            if action == "decrypt_file":
                return await self._decrypt_file(workspace_path, file_path, pw_file)
            if action == "encrypt_string":
                return await self._encrypt_string(content, variable_name, pw_file)
            if action == "create_encrypted":
                return await self._create_encrypted(workspace_path, file_path, content, pw_file)
            return ToolResult.fail(f"Unknown action: {action}")
        finally:
            Path(pw_file).unlink(missing_ok=True)

    @staticmethod
    def _write_password_file(password: str) -> str:
        fd, path = tempfile.mkstemp(prefix="vault_pw_")
        with open(fd, "w") as f:
            f.write(password)
        return path

    @staticmethod
    def _resolve_workspace_path(workspace: str, file_path: str) -> tuple[Path, str | None]:
        workspace_dir = Path(workspace).resolve()
        target = (workspace_dir / file_path).resolve()
        if not target.is_relative_to(workspace_dir):
            return target, f"Path escapes workspace: {file_path!r}"
        return target, None

    async def _encrypt_file(
        self, workspace: str, file_path: str, pw_file: str
    ) -> ToolResult:
        target, err = self._resolve_workspace_path(workspace, file_path)
        if err:
            return ToolResult.fail(err)
        if not target.exists():
            return ToolResult.fail(f"File not found: {target}")

        rc, stdout, stderr = await self._run_vault(
            "encrypt", str(target), f"--vault-password-file={pw_file}"
        )
        if rc != 0:
            return ToolResult.fail(f"Vault encrypt failed: {stderr}")
        return ToolResult.ok(output=f"Encrypted {target}", path=str(target))

    async def _decrypt_file(
        self, workspace: str, file_path: str, pw_file: str
    ) -> ToolResult:
        target, err = self._resolve_workspace_path(workspace, file_path)
        if err:
            return ToolResult.fail(err)
        if not target.exists():
            return ToolResult.fail(f"File not found: {target}")

        rc, stdout, stderr = await self._run_vault(
            "decrypt", str(target), f"--vault-password-file={pw_file}"
        )
        if rc != 0:
            return ToolResult.fail(f"Vault decrypt failed: {stderr}")
        return ToolResult.ok(output=f"Decrypted {target}", path=str(target))

    async def _encrypt_string(
        self, content: str, variable_name: str, pw_file: str
    ) -> ToolResult:
        if not content:
            return ToolResult.fail("content is required for encrypt_string")

        args = ["encrypt_string", content, f"--vault-password-file={pw_file}"]
        if variable_name:
            args.extend(["--name", variable_name])

        rc, stdout, stderr = await self._run_vault(*args)
        if rc != 0:
            return ToolResult.fail(f"Vault encrypt_string failed: {stderr}")
        return ToolResult.ok(output=stdout)

    async def _create_encrypted(
        self, workspace: str, file_path: str, content: str, pw_file: str
    ) -> ToolResult:
        if not file_path or not content:
            return ToolResult.fail("file_path and content are required for create_encrypted")

        target, err = self._resolve_workspace_path(workspace, file_path)
        if err:
            return ToolResult.fail(err)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        rc, stdout, stderr = await self._run_vault(
            "encrypt", str(target), f"--vault-password-file={pw_file}"
        )
        if rc != 0:
            return ToolResult.fail(f"Vault encrypt failed: {stderr}")
        return ToolResult.ok(output=f"Created encrypted file at {target}", path=str(target))

    @staticmethod
    async def _run_vault(*args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            "ansible-vault",
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
