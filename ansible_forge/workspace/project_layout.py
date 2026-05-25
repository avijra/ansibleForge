"""Ensure correct Ansible project structure within a workspace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def ensure_ansible_cfg(workspace_path: Path) -> Path:
    """Write a minimal ansible.cfg to the project directory if absent."""
    cfg_path = workspace_path / "ansible.cfg"
    if not cfg_path.exists():
        cfg_path.write_text(
            "[defaults]\n"
            "host_key_checking = False\n"
            "retry_files_enabled = False\n"
            "stdout_callback = yaml\n"
            "roles_path = roles\n"
            "\n"
            "[privilege_escalation]\n"
            "become = False\n",
            encoding="utf-8",
        )
    return cfg_path


def write_extravars(workspace_path: Path, extra_vars: dict[str, Any]) -> Path:
    """Write extra variables to the .tuyere/env/ directory."""
    env_dir = workspace_path / ".tuyere" / "env"
    env_dir.mkdir(parents=True, exist_ok=True)
    extravars_path = env_dir / "extravars"
    extravars_path.write_text(
        yaml.dump(extra_vars, default_flow_style=False), encoding="utf-8"
    )
    return extravars_path


def list_playbooks(workspace_path: Path) -> list[str]:
    """List all playbook YAML files in the project root and playbooks/ subdir."""
    if not workspace_path.exists():
        return []
    results: list[str] = []
    for search_dir in (workspace_path, workspace_path / "playbooks"):
        if not search_dir.is_dir():
            continue
        for f in search_dir.iterdir():
            if f.is_file() and f.suffix in (".yml", ".yaml") and not f.name.startswith("."):
                rel = str(f.relative_to(workspace_path))
                if rel not in results:
                    results.append(rel)
    return results
