"""Structured configuration collector — prompts the user with a form UI."""

from __future__ import annotations

from typing import Any

from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus


class ConfigRequester(BaseTool):
    @property
    def name(self) -> str:
        return "request_config"

    @property
    def description(self) -> str:
        return (
            "Collect structured non-secret configuration from the user via a form UI. "
            "Unlike request_secret, values are returned as plain text (visible to you). "
            "Use for cluster names, regions, instance types, node counts, and similar "
            "deployment parameters. Supports text, number, select, textarea, and boolean fields."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title for the configuration form (e.g. 'OpenShift Cluster Configuration')",
                },
                "fields": {
                    "type": "array",
                    "description": "List of configuration fields to collect",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "Machine-readable field name (e.g. 'cluster_name')",
                            },
                            "label": {
                                "type": "string",
                                "description": "Human-readable label (e.g. 'Cluster Name')",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["text", "number", "select", "textarea", "boolean"],
                                "description": "Input type",
                            },
                            "required": {
                                "type": "boolean",
                                "description": "Whether the field is required (default: false)",
                            },
                            "default": {
                                "description": "Default value for the field",
                            },
                            "placeholder": {
                                "type": "string",
                                "description": "Placeholder text for text/textarea inputs",
                            },
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Options for 'select' type fields",
                            },
                        },
                        "required": ["name", "label", "type"],
                    },
                },
            },
            "required": ["title", "fields"],
        }

    async def execute(
        self,
        title: str = "",
        fields: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not title or not fields:
            return ToolResult.fail("title and fields are required")

        for field in fields:
            if not field.get("name") or not field.get("label") or not field.get("type"):
                return ToolResult.fail(f"Each field must have name, label, and type. Invalid: {field}")
            if field["type"] == "select" and not field.get("options"):
                return ToolResult.fail(f"Select field '{field['name']}' requires 'options' list.")

        return ToolResult(
            status=ToolStatus.NEEDS_APPROVAL,
            output=f"Configuration required: {title}",
            data={
                "config_request": True,
                "title": title,
                "fields": fields,
            },
        )
