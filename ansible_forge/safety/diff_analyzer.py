"""Parse and present diffs from check-mode execution results."""

from __future__ import annotations

from typing import Any


class DiffAnalyzer:
    """Analyzes dry-run results and produces human-readable change summaries."""

    def analyze(self, events: list[dict[str, Any]]) -> DiffReport:
        changes: list[ChangeItem] = []
        for event in events:
            ev_type = event.get("event", "")
            result = event.get("result", {})
            host = event.get("host", "unknown")
            task = event.get("task", "unknown")

            if ev_type == "runner_on_changed":
                diff = result.get("diff", {})
                before_raw, after_raw = self._extract_before_after(diff)
                changes.append(
                    ChangeItem(
                        host=host,
                        task=task,
                        action="changed",
                        diff=self._format_diff(diff),
                        detail=result.get("msg", ""),
                        before=before_raw,
                        after=after_raw,
                    )
                )
            elif ev_type == "runner_on_ok" and result.get("changed"):
                changes.append(
                    ChangeItem(
                        host=host,
                        task=task,
                        action="would_change",
                        diff="",
                        detail=result.get("msg", ""),
                    )
                )
            elif ev_type == "runner_on_failed":
                changes.append(
                    ChangeItem(
                        host=host,
                        task=task,
                        action="would_fail",
                        diff="",
                        detail=result.get("msg", str(result.get("stderr", ""))),
                    )
                )

        return DiffReport(changes=changes)

    @staticmethod
    def _extract_before_after(diff: Any) -> tuple[str, str]:
        if isinstance(diff, dict):
            return str(diff.get("before", "")), str(diff.get("after", ""))
        return "", ""

    @staticmethod
    def _format_diff(diff: Any) -> str:
        if isinstance(diff, dict):
            before = diff.get("before", "")
            after = diff.get("after", "")
            if before or after:
                return f"--- before\n{before}\n+++ after\n{after}"
            before_header = diff.get("before_header", "")
            after_header = diff.get("after_header", "")
            if before_header or after_header:
                return f"--- {before_header}\n+++ {after_header}"
        if isinstance(diff, str):
            return diff
        if isinstance(diff, list):
            return "\n".join(str(d) for d in diff)
        return ""


class ChangeItem:
    def __init__(
        self, host: str, task: str, action: str, diff: str, detail: str,
        before: str = "", after: str = "",
    ) -> None:
        self.host = host
        self.task = task
        self.action = action
        self.diff = diff
        self.detail = detail
        self.before = before
        self.after = after

    def to_dict(self) -> dict[str, str]:
        return {
            "host": self.host,
            "task": self.task,
            "action": self.action,
            "diff": self.diff,
            "detail": self.detail,
            "before": self.before,
            "after": self.after,
        }


class DiffReport:
    def __init__(self, changes: list[ChangeItem]) -> None:
        self.changes = changes

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0

    @property
    def has_failures(self) -> bool:
        return any(c.action == "would_fail" for c in self.changes)

    def summary(self) -> str:
        if not self.changes:
            return "No changes detected."
        lines = [f"{len(self.changes)} change(s) detected:"]
        for c in self.changes:
            prefix = "FAIL" if c.action == "would_fail" else "CHANGE"
            lines.append(f"  [{prefix}] {c.host} / {c.task}: {c.detail or c.action}")
            if c.diff:
                for diff_line in c.diff.split("\n")[:10]:
                    lines.append(f"    {diff_line}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_count": len(self.changes),
            "has_failures": self.has_failures,
            "changes": [c.to_dict() for c in self.changes],
            "summary": self.summary(),
        }
