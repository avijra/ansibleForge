"""Detect missing secrets referenced by Jinja variables in inventory files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_JINJA_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_BUILTIN_VARS = frozenset({
    "ansible_playbook_python",
    "inventory_hostname",
    "ansible_host",
    "ansible_user",
    "ansible_port",
    "ansible_connection",
    "groups",
    "hostvars",
    "item",
})


def find_missing_secrets(
    inventory_path: Path,
    provided_vars: dict[str, Any],
) -> list[str]:
    try:
        content = inventory_path.read_text()
    except OSError:
        return []
    refs = set(_JINJA_VAR.findall(content))
    needed = refs - _BUILTIN_VARS
    return sorted(name for name in needed if name not in provided_vars)
