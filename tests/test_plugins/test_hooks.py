"""Tests for the plugin hook system."""

from __future__ import annotations

from pathlib import Path

from ansible_forge.plugins.hooks import (
    HookRegistry,
    load_hooks_from_directory,
)


class TestHookRegistry:
    def setup_method(self):
        HookRegistry._instance = None
        self.registry = HookRegistry.get_instance()

    def teardown_method(self):
        HookRegistry._instance = None

    def test_singleton(self):
        r2 = HookRegistry.get_instance()
        assert r2 is self.registry

    def test_register_and_fire(self):
        calls: list[str] = []

        def my_hook(tool_name: str, arguments: dict) -> None:
            calls.append(f"{tool_name}:{len(arguments)}")

        self.registry.register("before_tool_call", my_hook)
        self.registry.fire("before_tool_call", tool_name="test", arguments={"a": 1})
        assert calls == ["test:1"]

    def test_fire_returns_last_non_none(self):
        def hook_a(tool_name: str, arguments: dict) -> dict | None:
            return {"extra": "from_a"}

        def hook_b(tool_name: str, arguments: dict) -> dict | None:
            return None

        self.registry.register("before_tool_call", hook_a)
        self.registry.register("before_tool_call", hook_b)
        result = self.registry.fire("before_tool_call", tool_name="t", arguments={})
        assert result == {"extra": "from_a"}

    def test_unknown_event_ignored(self):
        self.registry.register("nonexistent_event", lambda: None)
        assert self.registry.hook_count == 0

    def test_hook_error_doesnt_propagate(self):
        def bad_hook(**kwargs):
            raise ValueError("boom")

        self.registry.register("on_error", bad_hook)
        result = self.registry.fire("on_error", tool_name="t", error_message="err")
        assert result is None

    def test_clear(self):
        self.registry.register("on_error", lambda **k: None)
        assert self.registry.hook_count > 0
        self.registry.clear()
        assert self.registry.hook_count == 0


class TestLoadHooksFromDirectory:
    def test_loads_hooks_from_py_files(self, tmp_path: Path):
        HookRegistry._instance = None
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "my_hook.py").write_text(
            "def on_session_start(session_id, workspace_path):\n"
            "    pass\n"
        )
        count = load_hooks_from_directory(hooks_dir)
        assert count == 1
        HookRegistry._instance = None

    def test_skips_underscored_files(self, tmp_path: Path):
        HookRegistry._instance = None
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "_private.py").write_text("def on_error(**k): pass\n")
        count = load_hooks_from_directory(hooks_dir)
        assert count == 0
        HookRegistry._instance = None

    def test_nonexistent_dir_returns_zero(self):
        HookRegistry._instance = None
        count = load_hooks_from_directory(Path("/nonexistent/hooks"))
        assert count == 0
        HookRegistry._instance = None
