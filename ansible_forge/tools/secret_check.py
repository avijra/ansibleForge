"""Detect missing secrets referenced by Jinja variables in inventory files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_JINJA_VAR = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_BUILTIN_VARS = frozenset({
    "ansible_host", "ansible_port", "ansible_user", "ansible_connection",
    "ansible_become", "ansible_become_user", "ansible_become_method",
    "ansible_become_password", "ansible_become_pass",
    "ansible_python_interpreter", "ansible_playbook_python",
    "ansible_ssh_private_key_file", "ansible_ssh_common_args",
    "ansible_ssh_extra_args", "ansible_ssh_pipelining",
    "ansible_ssh_pass", "ansible_password",
    "ansible_network_os", "ansible_httpapi_use_ssl",
    "ansible_httpapi_validate_certs",
    "ansible_winrm_server_cert_validation", "ansible_winrm_transport",
    "ansible_shell_type", "ansible_shell_executable",
    "inventory_hostname", "inventory_hostname_short", "group_names",
    "groups", "hostvars", "ansible_facts", "ansible_play_hosts",
    "ansible_play_hosts_all", "ansible_play_batch",
    "ansible_play_name", "ansible_role_name",
    "ansible_check_mode", "ansible_diff_mode", "ansible_verbosity",
    "ansible_version", "ansible_forks",
    "ansible_run_tags", "ansible_skip_tags",
    "ansible_search_path", "ansible_config_file",
    "item", "ansible_loop", "ansible_loop_var",
    "ansible_index_var", "ansible_parent_role_names",
    "role_path", "role_name", "playbook_dir",
    "omit", "undefined",
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
    missing = refs - _BUILTIN_VARS - provided
    missing = {v for v in missing if not v.startswith("ansible_")}
    return sorted(missing)
