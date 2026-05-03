"""User-editable rules API — read and write .tuyere/rules.md."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.workspace.resolver import resolve_workspace

router = APIRouter()

_DEFAULT_TEMPLATE = """\
# Tuyere Rules

Write rules here to customize how the agent behaves in this project.
These rules are injected into every agent conversation automatically.

## Examples

- Always use `ansible.builtin.command` instead of `ansible.builtin.shell`
- Never deploy on Fridays
- Use our internal Galaxy mirror at https://galaxy.internal.example.com
- All playbooks must have tags for every task
- Prefer Terraform for cloud resources, Ansible for configuration
"""


@router.get("/rules/{session_id}")
async def get_rules(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    rules_file = ws.runner_dir / "rules.md"
    exists = rules_file.is_file()
    content = rules_file.read_text() if exists else _DEFAULT_TEMPLATE

    return {
        "session_id": session_id,
        "content": content,
        "exists": exists,
        "path": str(rules_file),
    }


@router.put("/rules/{session_id}")
async def update_rules(
    session_id: str,
    body: dict[str, str],
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    content = body.get("content", "")
    rules_file = ws.runner_dir / "rules.md"
    rules_file.parent.mkdir(parents=True, exist_ok=True)
    rules_file.write_text(content)

    return {
        "session_id": session_id,
        "status": "saved",
        "path": str(rules_file),
    }
