"""Event hook system for plugin lifecycle integration.

Plugins can register hooks by placing Python files in their ``hooks/``
directory. Each file exports functions named after the event they handle:

    before_tool_call(tool_name, arguments) -> dict | None
    after_tool_call(tool_name, arguments, result) -> None
    on_session_start(session_id, workspace_path) -> None
    on_session_end(session_id, status) -> None
    on_plan_generated(session_id, plan) -> dict | None
    on_error(tool_name, error_message) -> str | None

Return values:
- ``before_tool_call``: return a dict to override arguments, or None to pass through.
- ``on_plan_generated``: return a modified plan dict, or None to pass through.
- ``on_error``: return a string with a recovery hint, or None.
- All others: return value is ignored.
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

HookFn = Callable[..., Any]

HOOK_EVENTS = frozenset({
    "before_tool_call",
    "after_tool_call",
    "on_session_start",
    "on_session_end",
    "on_plan_generated",
    "on_error",
})


class HookRegistry:
    _instance: HookRegistry | None = None

    def __init__(self) -> None:
        self._hooks: dict[str, list[HookFn]] = {event: [] for event in HOOK_EVENTS}

    @classmethod
    def get_instance(cls) -> HookRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, event: str, fn: HookFn) -> None:
        if event not in HOOK_EVENTS:
            logger.warning("unknown_hook_event", hook_event=event)
            return
        self._hooks[event].append(fn)
        logger.info("hook_registered", hook_event=event, fn=fn.__qualname__)

    def fire(self, event: str, **kwargs: Any) -> Any:
        if event not in self._hooks:
            return None
        result = None
        for fn in self._hooks[event]:
            try:
                r = fn(**kwargs)
                if r is not None:
                    result = r
            except Exception:
                logger.debug(
                    "hook_error", hook_event=event, fn=fn.__qualname__, exc_info=True
                )
        return result

    @property
    def hook_count(self) -> int:
        return sum(len(fns) for fns in self._hooks.values())

    def clear(self) -> None:
        for event in self._hooks:
            self._hooks[event].clear()


def load_hooks_from_directory(hooks_dir: Path) -> int:
    if not hooks_dir.is_dir():
        return 0
    registry = HookRegistry.get_instance()
    count = 0
    for py_file in sorted(hooks_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            module_name = f"tuyere_hook_{hooks_dir.parent.name}_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            for name, obj in inspect.getmembers(mod, inspect.isfunction):
                if name in HOOK_EVENTS:
                    registry.register(name, obj)
                    count += 1
        except Exception:
            logger.warning("hook_load_error", file=str(py_file), exc_info=True)
    return count
