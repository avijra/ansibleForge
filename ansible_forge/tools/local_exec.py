"""Local command execution tool — DISABLED.

All operations must use Ansible playbooks (execute_playbook) or Terraform
(terraform_exec). This tool exists in the schema so the LLM is aware of it,
but every invocation returns an error with guidance on the correct Ansible
module to use instead.
"""

from __future__ import annotations

from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_BLOCKED_MESSAGE = (
    "local_exec is disabled. ALL operations must use Ansible playbooks "
    "or Terraform.\n\n"
    "Write a playbook with the appropriate Ansible module:\n"
    "- File download: ansible.builtin.get_url\n"
    "- Archive extraction: ansible.builtin.unarchive\n"
    "- CLI tool execution: ansible.builtin.command (with creates:/when: guard)\n"
    "- File operations: ansible.builtin.copy / template / file / stat\n"
    "- Package install: ansible.builtin.pip / apt / dnf / yum\n"
    "- Service management: ansible.builtin.systemd / service\n"
    "- Cloud CLIs: use the matching cloud module (amazon.aws.*, azure.*, google.*)\n"
    "- Kubernetes/OpenShift: kubernetes.core.k8s / k8s_info\n"
    "- Docker: community.docker.*\n"
    "- Terraform: terraform_exec tool\n\n"
    "Then execute it with execute_playbook. "
    "There are NO exceptions — every operation has an Ansible module."
)


class LocalExec(BaseTool):
    @property
    def name(self) -> str:
        return "local_exec"

    @property
    def description(self) -> str:
        return (
            "DISABLED — do NOT use this tool. All operations must go through "
            "Ansible playbooks (execute_playbook) or Terraform (terraform_exec). "
            "Every shell command has an equivalent Ansible module: get_url for "
            "downloads, unarchive for extraction, command for CLI tools, k8s for "
            "Kubernetes, cloud modules for AWS/Azure/GCP. Write a playbook instead."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "DISABLED — write a playbook instead.",
                },
            },
            "required": ["command"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        command = kwargs.get("command", "")
        logger.warning("local_exec_blocked_permanent", command=str(command)[:200])
        return ToolResult.fail(_BLOCKED_MESSAGE)
