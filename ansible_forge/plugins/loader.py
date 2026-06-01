"""Dynamic plugin loader for Tuyere tool extensions.

Plugins live in ``~/.tuyere/plugins/`` or ``<workspace>/.tuyere/plugins/``.
Each plugin is a directory containing:

  plugin.yml    — metadata (name, version, description, author)
  tools/        — Python modules, each exporting a class inheriting ``BaseTool``

The loader scans plugin directories, imports tool classes, validates them,
and registers them into the provided ``ToolRegistry``.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

import yaml

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool
from ansible_forge.tools.registry import ToolRegistry

logger = get_logger(__name__)

_GLOBAL_PLUGIN_DIR = Path.home() / ".tuyere" / "plugins"


def _load_plugin_manifest(plugin_dir: Path) -> dict[str, Any] | None:
    manifest = plugin_dir / "plugin.yml"
    if not manifest.is_file():
        manifest = plugin_dir / "plugin.yaml"
    if not manifest.is_file():
        return None
    try:
        return yaml.safe_load(manifest.read_text()) or {}
    except Exception:
        logger.warning("plugin_manifest_parse_error", path=str(manifest), exc_info=True)
        return None


def _load_tools_from_directory(tools_dir: Path) -> list[BaseTool]:
    tools: list[BaseTool] = []
    if not tools_dir.is_dir():
        return tools

    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            module_name = f"tuyere_plugin_{py_file.parent.parent.name}_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            for _, obj in inspect.getmembers(mod, inspect.isclass):
                if (
                    issubclass(obj, BaseTool)
                    and obj is not BaseTool
                    and not inspect.isabstract(obj)
                ):
                    tool_instance = obj()
                    tools.append(tool_instance)
                    logger.info(
                        "plugin_tool_loaded",
                        tool=tool_instance.name,
                        source=str(py_file),
                    )
        except Exception:
            logger.warning("plugin_tool_load_error", file=str(py_file), exc_info=True)

    return tools


def load_plugins(
    registry: ToolRegistry,
    workspace_path: Path | None = None,
) -> list[dict[str, Any]]:
    loaded: list[dict[str, Any]] = []

    search_dirs = [_GLOBAL_PLUGIN_DIR]
    if workspace_path:
        ws_plugins = workspace_path / ".tuyere" / "plugins"
        if ws_plugins.is_dir():
            search_dirs.append(ws_plugins)

    for plugins_root in search_dirs:
        if not plugins_root.is_dir():
            continue

        for plugin_dir in sorted(plugins_root.iterdir()):
            if not plugin_dir.is_dir():
                continue

            manifest = _load_plugin_manifest(plugin_dir)
            if manifest is None:
                logger.debug("plugin_skipped_no_manifest", path=str(plugin_dir))
                continue

            plugin_name = manifest.get("name", plugin_dir.name)
            plugin_version = manifest.get("version", "0.0.0")

            tools = _load_tools_from_directory(plugin_dir / "tools")
            for tool in tools:
                registry.register(tool)

            hook_count = 0
            try:
                from ansible_forge.plugins.hooks import load_hooks_from_directory
                hook_count = load_hooks_from_directory(plugin_dir / "hooks")
            except Exception:
                logger.debug("plugin_hooks_load_error", plugin=plugin_name, exc_info=True)

            plugin_info = {
                "name": plugin_name,
                "version": plugin_version,
                "description": manifest.get("description", ""),
                "author": manifest.get("author", ""),
                "path": str(plugin_dir),
                "tools": [t.name for t in tools],
                "tool_count": len(tools),
                "hook_count": hook_count,
            }
            loaded.append(plugin_info)

            logger.info(
                "plugin_loaded",
                name=plugin_name,
                version=plugin_version,
                tools=[t.name for t in tools],
            )

    return loaded


def list_installed_plugins(workspace_path: Path | None = None) -> list[dict[str, Any]]:
    plugins: list[dict[str, Any]] = []

    search_dirs = [_GLOBAL_PLUGIN_DIR]
    if workspace_path:
        ws_plugins = workspace_path / ".tuyere" / "plugins"
        if ws_plugins.is_dir():
            search_dirs.append(ws_plugins)

    for plugins_root in search_dirs:
        if not plugins_root.is_dir():
            continue

        for plugin_dir in sorted(plugins_root.iterdir()):
            if not plugin_dir.is_dir():
                continue

            manifest = _load_plugin_manifest(plugin_dir)
            if manifest is None:
                continue

            tool_count = sum(
                1 for f in (plugin_dir / "tools").glob("*.py")
                if not f.name.startswith("_")
            ) if (plugin_dir / "tools").is_dir() else 0

            plugins.append({
                "name": manifest.get("name", plugin_dir.name),
                "version": manifest.get("version", "0.0.0"),
                "description": manifest.get("description", ""),
                "author": manifest.get("author", ""),
                "path": str(plugin_dir),
                "tool_count": tool_count,
                "scope": "global" if plugins_root == _GLOBAL_PLUGIN_DIR else "workspace",
            })

    return plugins
