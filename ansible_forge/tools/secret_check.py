"""Detect missing secrets referenced by Jinja variables in inventory files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_JINJA_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_BUILTIN_VARS = frozenset({
    "ansible_host", "ansible_port", "ansible_user", "ansible_connection",
    "ansible_become", "ansible_become_user", "ansible_become_method",
    "inventory_hostname", "inventory_hostname_short", "group_names",
    "groups", "hostvars", "ansible_facts", "ansible_play_hosts",
    "item", "ansible_loop",
})


def find_missing_secrets(
    inventory_path: Path | str, extra_vars: dict[str, Any] | None = None,
) -> list[str]:
    inv = Path(inventory_path)
    if not inv.exists():
        return []
    try:
        text = inv.read_text(errors="replace")
    except Exception:
        return []
    refs = set(_JINJA_VAR.findall(text))
    provided = set((extra_vars or {}).keys())
    return sorted(refs - _BUILTIN_VARS - provided)
