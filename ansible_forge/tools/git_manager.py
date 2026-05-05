"""Git version control operations scoped to workspace directories."""

from __future__ import annotations

import asyncio
import functools
import subprocess
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_VALID_ACTIONS = ("init", "status", "diff", "add", "commit", "log", "branch", "checkout", "push", "pull", "stash")


class GitManager(BaseTool):
    @property
    def name(self) -> str:
        return "manage_git"

    @property
    def description(self) -> str:
        return (
            "Manage Git version control for workspace projects. Supports init, status, "
            "diff, add, commit, log, branch, checkout, push, pull, and stash operations. "
            "All operations are scoped to the workspace project directory for safety."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory",
                },
                "action": {
                    "type": "string",
                    "enum": list(_VALID_ACTIONS),
                    "description": "Git action to perform",
                },
                "message": {
                    "type": "string",
                    "description": "Commit message (for 'commit' action)",
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File paths to stage (for 'add' action). Use ['.'] for all files.",
                },
                "branch_name": {
                    "type": "string",
                    "description": "Branch name (for 'branch' or 'checkout' action)",
                },
                "remote": {
                    "type": "string",
                    "description": "Remote name for push/pull (default: 'origin')",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of log entries to show (default: 10)",
                    "minimum": 1,
                    "maximum": 50,
                },
            },
            "required": ["workspace_path", "action"],
        }

    async def execute(
        self,
        workspace_path: str = "",
        action: str = "",
        message: str = "",
        files: list[str] | None = None,
        branch_name: str = "",
        remote: str = "origin",
        count: int = 10,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not action:
            return ToolResult.fail("workspace_path and action are required")

        if action not in _VALID_ACTIONS:
            return ToolResult.fail(f"Invalid action: {action}. Must be one of: {', '.join(_VALID_ACTIONS)}")

        project_dir = Path(workspace_path)

        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            return ToolResult.fail(f"Action '{action}' not implemented")

        return await handler(
            project_dir,
            message=message,
            files=files,
            branch_name=branch_name,
            remote=remote,
            count=count,
        )

    async def _run_git(self, cwd: Path, *args: str, timeout: int = 30) -> tuple[int, str, str]:
        cmd = ["git"] + list(args)
        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    functools.partial(
                        subprocess.run, cmd,
                        cwd=str(cwd),
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                    ),
                ),
                timeout=timeout + 5,
            )
            return result.returncode, result.stdout, result.stderr
        except (TimeoutError, subprocess.TimeoutExpired):
            return 1, "", "Git command timed out"

    async def _do_init(self, cwd: Path, **_: Any) -> ToolResult:
        if (cwd / ".git").exists():
            return ToolResult.ok(output="Repository already initialized")
        rc, out, err = await self._run_git(cwd, "init")
        if rc != 0:
            return ToolResult.fail(f"git init failed: {err}")
        return ToolResult.ok(output=f"Initialized git repository in {cwd}", stdout=out)

    async def _do_status(self, cwd: Path, **_: Any) -> ToolResult:
        rc, out, err = await self._run_git(cwd, "status", "--porcelain=v1")
        if rc != 0:
            return ToolResult.fail(f"git status failed: {err}")

        branch_rc, branch_out, _ = await self._run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch_out.strip() if branch_rc == 0 else "unknown"

        lines = [line for line in out.strip().splitlines() if line.strip()]
        staged = [line for line in lines if line[0] != " " and line[0] != "?"]
        unstaged = [line for line in lines if len(line) > 1 and line[1] != " " and line[0] != "?"]
        untracked = [line for line in lines if line.startswith("??")]

        return ToolResult.ok(
            output=f"Branch: {branch} | {len(staged)} staged, {len(unstaged)} modified, {len(untracked)} untracked",
            branch=branch,
            staged=[line[3:] for line in staged],
            modified=[line[3:] for line in unstaged],
            untracked=[line[3:] for line in untracked],
            raw=out[:3000],
        )

    async def _do_diff(self, cwd: Path, **_: Any) -> ToolResult:
        rc, staged_diff, err = await self._run_git(cwd, "diff", "--cached", "--stat")
        if rc != 0:
            return ToolResult.fail(f"git diff --cached failed: {err}")
        rc2, unstaged_diff, err2 = await self._run_git(cwd, "diff", "--stat")
        if rc2 != 0:
            return ToolResult.fail(f"git diff failed: {err2}")
        rc3, full_diff, err3 = await self._run_git(cwd, "diff")
        if rc3 != 0:
            return ToolResult.fail(f"git diff failed: {err3}")

        return ToolResult.ok(
            output=f"Diff generated ({len(full_diff)} chars)",
            staged_summary=staged_diff[:2000],
            unstaged_summary=unstaged_diff[:2000],
            full_diff=full_diff[:8000],
        )

    async def _do_add(self, cwd: Path, files: list[str] | None = None, **_: Any) -> ToolResult:
        targets = files or ["."]
        rc, out, err = await self._run_git(cwd, "add", *targets)
        if rc != 0:
            return ToolResult.fail(f"git add failed: {err}")
        return ToolResult.ok(output=f"Staged: {', '.join(targets)}")

    async def _do_commit(self, cwd: Path, message: str = "", **_: Any) -> ToolResult:
        if not message:
            return ToolResult.fail("Commit message is required")
        rc, out, err = await self._run_git(cwd, "commit", "-m", message)
        if rc != 0:
            return ToolResult.fail(f"git commit failed: {err.strip() or out.strip()}")
        return ToolResult.ok(output=f"Committed: {out.strip()}", stdout=out)

    async def _do_log(self, cwd: Path, count: int = 10, **_: Any) -> ToolResult:
        rc, out, err = await self._run_git(
            cwd, "log", f"--max-count={count}",
            "--format=%h %s (%cr) <%an>",
        )
        if rc != 0:
            return ToolResult.fail(f"git log failed: {err}")
        entries = [line.strip() for line in out.strip().splitlines() if line.strip()]
        return ToolResult.ok(
            output=f"Showing {len(entries)} commit(s)",
            commits=entries,
        )

    async def _do_branch(self, cwd: Path, branch_name: str = "", **_: Any) -> ToolResult:
        if branch_name:
            rc, out, err = await self._run_git(cwd, "branch", branch_name)
            if rc != 0:
                return ToolResult.fail(f"git branch failed: {err}")
            return ToolResult.ok(output=f"Created branch: {branch_name}")

        rc, out, err = await self._run_git(cwd, "branch", "-a")
        if rc != 0:
            return ToolResult.fail(f"git branch failed: {err}")
        branches = [line.strip() for line in out.strip().splitlines() if line.strip()]
        return ToolResult.ok(output=f"{len(branches)} branch(es)", branches=branches)

    async def _do_checkout(self, cwd: Path, branch_name: str = "", **_: Any) -> ToolResult:
        if not branch_name:
            return ToolResult.fail("branch_name is required for checkout")
        rc, out, err = await self._run_git(cwd, "checkout", branch_name)
        if rc != 0:
            rc, out, err = await self._run_git(cwd, "checkout", "-b", branch_name)
        if rc != 0:
            return ToolResult.fail(f"git checkout failed: {err}")
        return ToolResult.ok(output=f"Switched to branch: {branch_name}")

    async def _do_push(self, cwd: Path, remote: str = "origin", branch_name: str = "", **_: Any) -> ToolResult:
        args = ["push", remote]
        if branch_name:
            args.append(branch_name)
        rc, out, err = await self._run_git(cwd, *args, timeout=60)
        if rc != 0:
            return ToolResult.fail(f"git push failed: {err}")
        return ToolResult.ok(output=f"Pushed to {remote}", stdout=out or err)

    async def _do_pull(self, cwd: Path, remote: str = "origin", branch_name: str = "", **_: Any) -> ToolResult:
        args = ["pull", remote]
        if branch_name:
            args.append(branch_name)
        rc, out, err = await self._run_git(cwd, *args, timeout=60)
        if rc != 0:
            return ToolResult.fail(f"git pull failed: {err}")
        return ToolResult.ok(output=f"Pulled from {remote}", stdout=out)

    async def _do_stash(self, cwd: Path, message: str = "", **_: Any) -> ToolResult:
        args = ["stash"]
        if message:
            args.extend(["push", "-m", message])
        rc, out, err = await self._run_git(cwd, *args)
        if rc != 0:
            return ToolResult.fail(f"git stash failed: {err}")
        return ToolResult.ok(output=out.strip() or "Stash applied")
