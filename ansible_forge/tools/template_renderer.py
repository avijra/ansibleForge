"""Preview Jinja2 templates with real host variables before deploying."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import BaseLoader, Environment, StrictUndefined, Undefined, UndefinedError

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


def _ansible_filters() -> dict[str, Any]:
    """Provide common Ansible/Jinja2 filters for realistic rendering."""

    def _default(value: Any, default_value: Any = "", boolean: bool = False) -> Any:
        if boolean:
            return value if value else default_value
        return value if value is not None else default_value

    def _regex_replace(value: str, pattern: str, replacement: str) -> str:
        import re
        return re.sub(pattern, replacement, value)

    def _combine(*dicts: dict, recursive: bool = False) -> dict:
        result: dict = {}
        for d in dicts:
            if isinstance(d, dict):
                if recursive:
                    for k, v in d.items():
                        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
                            result[k] = _combine(result[k], v, recursive=True)
                        else:
                            result[k] = v
                else:
                    result.update(d)
        return result

    def _to_nice_json(value: Any, indent: int = 4) -> str:
        return json.dumps(value, indent=indent, sort_keys=True)

    def _to_nice_yaml(value: Any) -> str:
        import yaml
        return yaml.dump(value, default_flow_style=False)

    def _split(value: str, separator: str = " ") -> list[str]:
        return value.split(separator)

    def _join(value: list, separator: str = "") -> str:
        return separator.join(str(v) for v in value)

    def _basename(path: str) -> str:
        return Path(path).name

    def _dirname(path: str) -> str:
        return str(Path(path).parent)

    def _bool_filter(value: Any) -> bool:
        if isinstance(value, str):
            return value.lower() in ("true", "yes", "1", "on")
        return bool(value)

    def _ipaddr(value: str, query: str = "") -> str:
        return value

    return {
        "default": _default,
        "d": _default,
        "regex_replace": _regex_replace,
        "combine": _combine,
        "to_nice_json": _to_nice_json,
        "to_json": lambda v: json.dumps(v),
        "to_nice_yaml": _to_nice_yaml,
        "to_yaml": _to_nice_yaml,
        "split": _split,
        "join": _join,
        "basename": _basename,
        "dirname": _dirname,
        "bool": _bool_filter,
        "ipaddr": _ipaddr,
        "mandatory": lambda v: v,
        "hash": lambda v, algo="sha256": __import__("hashlib").new(algo, str(v).encode()).hexdigest(),
        "b64encode": lambda v: __import__("base64").b64encode(str(v).encode()).decode(),
        "b64decode": lambda v: __import__("base64").b64decode(str(v).encode()).decode(),
        "quote": lambda v: __import__("shlex").quote(str(v)),
        "regex_search": lambda v, p: __import__("re").search(p, v) is not None,
        "ternary": lambda v, t, f: t if v else f,
        "comment": lambda v, prefix="# ": "\n".join(f"{prefix}{line}" for line in str(v).splitlines()),
        "flatten": lambda v, levels=1: _flatten(v, levels),
        "unique": lambda v: list(dict.fromkeys(v)),
        "sort": sorted,
        "reverse": lambda v: list(reversed(v)) if isinstance(v, list) else str(v)[::-1],
        "map": lambda v, *a, **kw: v,
        "select": lambda v, *a: v,
        "reject": lambda v, *a: v,
        "selectattr": lambda v, *a: v,
    }


def _flatten(lst: list, levels: int = 1) -> list:
    result: list = []
    for item in lst:
        if isinstance(item, list) and levels > 0:
            result.extend(_flatten(item, levels - 1))
        else:
            result.append(item)
    return result


class TemplateRenderer(BaseTool):
    @property
    def name(self) -> str:
        return "render_template"

    @property
    def description(self) -> str:
        return (
            "Preview a Jinja2 template rendered with real variables. Takes template "
            "content (or reads from workspace path) and a variable context to produce "
            "the rendered output. Reports undefined variables so you can fix templates "
            "before deploying. Supports common Ansible filters."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "template_content": {
                    "type": "string",
                    "description": (
                        "Raw Jinja2 template content to render. "
                        "Provide this OR template_path, not both."
                    ),
                },
                "template_path": {
                    "type": "string",
                    "description": (
                        "Path to a .j2 template file relative to the workspace project/ dir. "
                        "Provide this OR template_content, not both."
                    ),
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory (needed for template_path or host facts)",
                },
                "variables": {
                    "type": "object",
                    "description": "Variable context for rendering (key-value pairs)",
                    "additionalProperties": {},
                },
                "host": {
                    "type": "string",
                    "description": (
                        "Hostname to load cached facts for (from workspace artifacts/host_facts.json). "
                        "Facts are merged into the variable context."
                    ),
                },
                "strict": {
                    "type": "boolean",
                    "description": "If true, fail on undefined variables. Default: false (shows warnings instead)",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        template_content: str = "",
        template_path: str = "",
        workspace_path: str = "",
        variables: dict[str, Any] | None = None,
        host: str = "",
        strict: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if not template_content and not template_path:
            return ToolResult.fail("Provide either template_content or template_path")

        if template_path and not workspace_path:
            return ToolResult.fail("workspace_path is required when using template_path")

        if template_path:
            full_path = Path(workspace_path) / template_path
            if not full_path.exists():
                return ToolResult.fail(f"Template file not found: {template_path}")
            template_content = full_path.read_text(encoding="utf-8")

        context: dict[str, Any] = {}

        if host and workspace_path:
            facts_file = Path(workspace_path) / ".tuyere" / "artifacts" / "host_facts.json"
            if facts_file.exists():
                try:
                    all_facts = json.loads(facts_file.read_text(encoding="utf-8"))
                    host_facts = all_facts.get(host, {})
                    for k, v in host_facts.items():
                        context[f"ansible_{k}" if not k.startswith("ansible_") else k] = v
                except (json.JSONDecodeError, OSError):
                    logger.debug("host_facts_load_failed", exc_info=True)
                context["inventory_hostname"] = host

        if variables:
            context.update(variables)

        env = Environment(
            loader=BaseLoader(),
            undefined=StrictUndefined if strict else _LenientUndefined,
            keep_trailing_newline=True,
        )
        env.filters.update(_ansible_filters())

        warnings: list[str] = []

        try:
            tmpl = env.from_string(template_content)
            rendered = tmpl.render(**context)
        except UndefinedError as exc:
            return ToolResult.fail(
                f"Undefined variable: {exc}",
                template_preview=template_content[:500],
                available_variables=sorted(context.keys()),
            )
        except Exception as exc:
            return ToolResult.fail(
                f"Template rendering failed: {exc}",
                template_preview=template_content[:500],
            )

        if hasattr(env, "_undefined_vars"):
            warnings = list(env._undefined_vars)

        return ToolResult.ok(
            output=f"Template rendered successfully ({len(rendered)} chars, {len(warnings)} warning(s))",
            rendered=rendered[:10000],
            warnings=warnings,
            variable_count=len(context),
        )


class _LenientUndefined(Undefined):
    """Tracks access to undefined variables without raising errors.

    Must extend jinja2.Undefined so Environment accepts it.
    """

    def __str__(self) -> str:
        return f"{{{{ {self._undefined_name or 'undefined'} }}}}"

    def __iter__(self):
        return iter([])

    def __bool__(self) -> bool:
        return False

    def __getattr__(self, name: str) -> _LenientUndefined:
        if name.startswith("_"):
            raise AttributeError(name)
        return _LenientUndefined(
            name=f"{self._undefined_name}.{name}" if self._undefined_name else name,
            hint=self._undefined_hint,
        )

    def __getitem__(self, name: str) -> _LenientUndefined:
        return _LenientUndefined(
            name=f"{self._undefined_name}[{name!r}]" if self._undefined_name else str(name),
            hint=self._undefined_hint,
        )

    def __call__(self, *args: Any, **kwargs: Any) -> _LenientUndefined:
        return self

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, _LenientUndefined)

    def __ne__(self, other: Any) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return id(self)

    def __len__(self) -> int:
        return 0

    def __contains__(self, item: Any) -> bool:
        return False
