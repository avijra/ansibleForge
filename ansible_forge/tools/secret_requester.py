"""Tool that lets the agent request secrets from the user without exposing them to the LLM."""

from __future__ import annotations

from typing import Any

from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus


class SecretRequester(BaseTool):
    """Request a secret value from the user through a secure UI prompt.

    The returned ToolResult carries a ``secret_request`` flag so the orchestrator
    knows to pause the loop, yield a ``secret_request`` SSE event, and wait for
    the user to submit the value through the dedicated secrets API.  The LLM
    never sees the actual secret — only a confirmation with the variable name.
    """

    @property
    def name(self) -> str:
        return "request_secret"

    @property
    def description(self) -> str:
        return (
            "Request a secret or credential from the user through a secure input prompt. "
            "Use this whenever you need passwords, API keys, tokens, pull secrets, SSH keys, "
            "or any sensitive value. The user will be shown a secure password input in the UI. "
            "You will receive a confirmation with the variable name to use in playbooks — "
            "the actual value is NEVER sent to you. Use the variable name in playbooks/templates "
            "and the real value will be injected at execution time."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Variable name for the secret (snake_case, no spaces). "
                        "This is the Ansible variable name you will reference in "
                        "playbooks/templates. For per-host credentials, prefix with "
                        "the host name: e.g. 'fedora_vm_ssh_password', 'ubuntu_vm_ssh_key'. "
                        "For shared credentials: 'ssh_private_key', 'api_token', 'db_password'."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Human-readable description shown to the user explaining what "
                        "this secret is for. Be specific so the user knows exactly what "
                        "to provide. Example: 'OpenShift pull secret JSON from cloud.redhat.com'"
                    ),
                },
                "sensitive_type": {
                    "type": "string",
                    "enum": ["password", "token", "key", "certificate", "json", "other"],
                    "description": "Category of secret — helps the UI choose the right input mode",
                },
                "for_host": {
                    "type": "string",
                    "description": (
                        "Host or group this credential applies to. When set, the UI shows "
                        "which host the user is providing credentials for. Examples: "
                        "'fedora-vm', '192.168.64.3', 'aws_hosts'. Leave empty for "
                        "shared/global credentials."
                    ),
                },
            },
            "required": ["name", "description"],
        }

    async def execute(
        self,
        name: str = "",
        description: str = "",
        sensitive_type: str = "other",
        for_host: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not name or not description:
            return ToolResult.fail("name and description are required")

        if not name.replace("_", "").isalnum():
            return ToolResult.fail(
                f"Secret name must be alphanumeric with underscores: got '{name}'"
            )

        display_desc = description
        if for_host:
            display_desc = f"[{for_host}] {description}"

        return ToolResult(
            status=ToolStatus.NEEDS_APPROVAL,
            output=f"Requesting secret '{name}' from user: {display_desc}",
            data={
                "secret_request": True,
                "secret_name": name,
                "secret_description": display_desc,
                "sensitive_type": sensitive_type,
                "for_host": for_host,
            },
        )
