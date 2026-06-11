"""Run ansible-lint on playbooks/roles and parse results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus

logger = get_logger(__name__)

PROFILES = ("min", "basic", "moderate", "safety", "shared", "production")


class LintRunner(BaseTool):
    @property
    def name(self) -> str:
        return "run_lint"

    @property
    def description(self) -> str:
        return (
            "Run ansible-lint on a playbook, role, or directory to check for best-practice "
            "violations. Returns structured violations with rule IDs, severity, file/line, "
            "and suggested fixes. Supports profiles: min, basic, moderate, safety, shared, production."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Path to playbook, role dir, or workspace to lint",
                },
                "workspace_path": {
                    "type": "string",
                    "description": (
                        "Absolute path to the workspace project directory. "
                        "Required when target is relative to the workspace."
                    ),
                },
                "profile": {
                    "type": "string",
                    "enum": list(PROFILES),
                    "description": "Lint profile strictness level (default: moderate)",
                },
                "auto_fix": {
                    "type": "boolean",
                    "description": "Attempt to auto-fix violations (default: false)",
                },
            },
            "required": ["target"],
        }

    @staticmethod
    def _resolve_target(target: str, workspace_path: str) -> Path:
        raw = Path(target)
        if raw.is_absolute() and raw.exists():
            return raw

        if workspace_path:
            ws = Path(workspace_path)
            candidates = [
                ws / target,
                ws / "playbooks" / target,
                ws / "roles" / target,
            ]
            for candidate in candidates:
                if candidate.exists():
                    return candidate
            if not raw.is_absolute():
                return ws / target

        return raw

    async def execute(
        self,
        target: str = "",
        profile: str = "moderate",
        auto_fix: bool = False,
        workspace_path: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not target:
            return ToolResult.fail("target path is required")

        target_path = self._resolve_target(target, workspace_path)
        if not target_path.exists():
            hint = (
                f" Use workspace_path='{workspace_path}' with a workspace-relative target."
                if workspace_path
                else " Provide workspace_path when using a relative target."
            )
            return ToolResult.fail(f"Target not found: {target_path}.{hint}")

        args = [
            "ansible-lint",
            str(target_path),
            f"--profile={profile}",
            "--format=json",
            "--nocolor",
        ]
        if auto_fix:
            args.append("--fix")

        from ansible_forge.tools.ee_runtime import ee_exec

        ws = Path(workspace_path) if workspace_path else None
        cwd = ws or (target_path.parent if target_path.is_file() else target_path)
        rc, stdout, stderr = await ee_exec(args, cwd=cwd, timeout=120, ws=ws)

        if "timed out" in stderr:
            return ToolResult.fail(f"ansible-lint timed out after 2 minutes. {stderr}")

        violations = self._parse_output(stdout)
        count = len(violations)

        if rc == 0:
            return ToolResult.ok(
                output=f"Lint passed ({profile} profile) — no violations found.",
                violations=violations,
                violation_count=0,
                profile=profile,
            )

        if count == 0 and rc != 0:
            return ToolResult.fail(
                f"ansible-lint exited with code {rc}. {stderr.strip()}"
            )

        return ToolResult(
            status=ToolStatus.ERROR,
            output=f"Lint found {count} violation(s) with profile '{profile}'.",
            error=f"{count} lint violation(s) found",
            data={
                "violations": violations,
                "violation_count": count,
                "profile": profile,
                "stderr": stderr if not violations else "",
            },
        )

    @staticmethod
    def _parse_output(stdout: str) -> list[dict[str, Any]]:
        if not stdout.strip():
            return []
        try:
            raw = json.loads(stdout)
            if isinstance(raw, list):
                return [
                    {
                        "rule": v.get("rule", {}).get("id", "unknown"),
                        "severity": v.get("rule", {}).get("severity", "unknown"),
                        "message": v.get("message", ""),
                        "filename": v.get("filename", ""),
                        "line": v.get("linenumber", 0),
                    }
                    for v in raw
                ]
        except json.JSONDecodeError:
            logger.debug("lint_json_parse_failed", raw=stdout[:500])
        return []
