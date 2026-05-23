"""Pre-execution validation rules to catch dangerous patterns before running."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, TemplateSyntaxError

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_JINJA_ENV = Environment(
    variable_start_string="{{",
    variable_end_string="}}",
    block_start_string="{%",
    block_end_string="%}",
    comment_start_string="{#",
    comment_end_string="#}",
    keep_trailing_newline=True,
)


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    rule: str
    message: str
    file: str = ""
    line: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
            "file": self.file,
            "line": self.line,
        }


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
        }


DANGEROUS_PATTERNS = [
    (r"rm\s+-rf\s+/(?:\s|$|;)", "Destructive rm -rf / detected"),
    (r"mkfs\.", "Filesystem formatting command detected"),
    (r"dd\s+if=.*of=/dev/", "Raw disk write with dd detected"),
    (r">\s*/dev/sd[a-z]", "Direct write to block device detected"),
    (r"shutdown|reboot|poweroff|halt", "System shutdown/reboot command detected"),
]

PRIVILEGE_ESCALATION_MODULES = frozenset({
    "ansible.builtin.command",
    "ansible.builtin.shell",
    "ansible.builtin.raw",
    "ansible.builtin.script",
})


class PlaybookValidator:
    """Validates playbooks against safety rules before execution."""

    def validate(self, workspace_path: str, playbook_name: str) -> ValidationResult:
        issues: list[ValidationIssue] = []
        playbook_path = Path(workspace_path) / playbook_name

        if not playbook_path.exists():
            return ValidationResult(
                passed=False,
                issues=[
                    ValidationIssue(
                        severity="error",
                        rule="file_not_found",
                        message=f"Playbook not found: {playbook_path}",
                    )
                ],
            )

        try:
            content = playbook_path.read_text(encoding="utf-8")
        except OSError as exc:
            return ValidationResult(
                passed=False,
                issues=[
                    ValidationIssue(
                        severity="error",
                        rule="file_read_error",
                        message=str(exc),
                    )
                ],
            )

        try:
            plays = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return ValidationResult(
                passed=False,
                issues=[
                    ValidationIssue(
                        severity="error",
                        rule="invalid_yaml",
                        message=f"Invalid YAML: {exc}",
                        file=str(playbook_path),
                    )
                ],
            )

        if not isinstance(plays, list):
            return ValidationResult(
                passed=False,
                issues=[
                    ValidationIssue(
                        severity="error",
                        rule="invalid_playbook",
                        message="Playbook must be a YAML list of plays",
                        file=str(playbook_path),
                    )
                ],
            )

        issues.extend(self._check_dangerous_patterns(content, str(playbook_path)))
        issues.extend(self._check_plays(plays, str(playbook_path)))

        project_dir = playbook_path.parent
        issues.extend(self._check_referenced_templates(plays, project_dir))

        has_errors = any(i.severity == "error" for i in issues)
        return ValidationResult(passed=not has_errors, issues=issues)

    def _check_dangerous_patterns(
        self, content: str, filepath: str
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for pattern, message in DANGEROUS_PATTERNS:
            if re.search(pattern, content):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        rule="dangerous_pattern",
                        message=message,
                        file=filepath,
                    )
                )
        return issues

    def _check_plays(
        self, plays: list[dict[str, Any]], filepath: str
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for play in plays:
            if play.get("become") and play.get("hosts") == "all":
                issues.append(
                    ValidationIssue(
                        severity="warning",
                        rule="broad_privilege_escalation",
                        message="Play uses 'become: true' on 'hosts: all' — review carefully",
                        file=filepath,
                    )
                )
            for task in play.get("tasks", []):
                issues.extend(self._check_task(task, filepath))
        return issues

    def _check_task(
        self, task: dict[str, Any], filepath: str
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for module in PRIVILEGE_ESCALATION_MODULES:
            params = task.get(module)
            if params is None:
                continue
            cmd = ""
            if isinstance(params, str):
                cmd = params
            elif isinstance(params, dict):
                cmd = params.get("cmd", "") or params.get("_raw_params", "")

            if cmd:
                for pattern, message in DANGEROUS_PATTERNS:
                    if re.search(pattern, cmd):
                        issues.append(
                            ValidationIssue(
                                severity="error",
                                rule="dangerous_command",
                                message=f"Task '{task.get('name', 'unnamed')}': {message}",
                                file=filepath,
                            )
                        )

            issues.append(
                ValidationIssue(
                    severity="warning",
                    rule="raw_command_usage",
                    message=(
                        f"Task '{task.get('name', 'unnamed')}' uses '{module}'. "
                        "Consider using a dedicated module instead."
                    ),
                    file=filepath,
                )
            )

        self._check_unencrypted_secrets(task, filepath, issues)
        return issues

    def _check_referenced_templates(
        self, plays: list[dict[str, Any]], project_dir: Path
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        template_srcs = self._extract_template_sources(plays)
        for src in template_srcs:
            issues.extend(
                self._validate_template_file(src, project_dir)
            )
        return issues

    def _extract_template_sources(
        self, plays: list[dict[str, Any]]
    ) -> set[str]:
        sources: set[str] = set()
        for play in plays:
            for task in play.get("tasks", []):
                self._collect_template_src(task, sources)
            for role_entry in play.get("roles", []):
                role_name = (
                    role_entry.get("role")
                    if isinstance(role_entry, dict)
                    else role_entry
                )
                if role_name:
                    sources.add(f"__role__:{role_name}")
        return sources

    def _collect_template_src(
        self, task: dict[str, Any], sources: set[str]
    ) -> None:
        tpl = task.get("ansible.builtin.template") or task.get("template")
        if isinstance(tpl, dict) and "src" in tpl:
            sources.add(tpl["src"])
        for block_key in ("block", "rescue", "always"):
            for sub in task.get(block_key, []):
                if isinstance(sub, dict):
                    self._collect_template_src(sub, sources)

    def _validate_template_file(
        self, src: str, project_dir: Path
    ) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if src.startswith("__role__:"):
            role_name = src[len("__role__:"):]
            templates_dir = project_dir / "roles" / role_name / "templates"
            if not templates_dir.is_dir():
                return issues
            for tpl_path in templates_dir.rglob("*.j2"):
                issues.extend(self._lint_single_template(tpl_path))
            return issues

        candidates = [
            project_dir / src,
            project_dir / "templates" / src,
        ]
        for candidate in candidates:
            if candidate.is_file():
                issues.extend(self._lint_single_template(candidate))
                return issues
        return issues

    @staticmethod
    def _lint_single_template(path: Path) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return issues
        try:
            _JINJA_ENV.parse(source)
        except TemplateSyntaxError as exc:
            issues.append(
                ValidationIssue(
                    severity="error",
                    rule="jinja2_syntax_error",
                    message=(
                        f"Jinja2 syntax error in template '{path.name}': "
                        f"{exc.message} (line {exc.lineno})"
                    ),
                    file=str(path),
                    line=exc.lineno or 0,
                )
            )
        return issues

    @staticmethod
    def _check_unencrypted_secrets(
        task: dict[str, Any], filepath: str, issues: list[ValidationIssue]
    ) -> None:
        secret_patterns = re.compile(
            r"(password|secret|token|api_key|private_key)", re.IGNORECASE
        )
        task_str = str(task)
        if (
            secret_patterns.search(task_str)
            and "$ANSIBLE_VAULT" not in task_str
            and "vault" not in task_str.lower()
            and "lookup" not in task_str.lower()
        ):
            issues.append(
                ValidationIssue(
                    severity="info",
                    rule="potential_unencrypted_secret",
                    message=(
                        f"Task '{task.get('name', 'unnamed')}' contains "
                        "credentials in plaintext. Vault encryption is "
                        "recommended but not required — proceeding as configured."
                    ),
                    file=filepath,
                )
            )
