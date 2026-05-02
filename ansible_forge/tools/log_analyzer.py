"""Analyze run history for patterns — failure hotspots, flaky hosts, trends."""

from __future__ import annotations

import datetime
import json
from collections import Counter
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.persistence.infrastructure_store import InfrastructureStore
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class LogAnalyzer(BaseTool):
    @property
    def name(self) -> str:
        return "analyze_logs"

    @property
    def description(self) -> str:
        return (
            "Analyze run history from the infrastructure store to identify patterns: "
            "which playbooks fail most, which hosts are flaky, average run times, "
            "success/failure ratios, and recent trends. Helps diagnose recurring issues "
            "and suggest improvements."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "analysis_type": {
                    "type": "string",
                    "enum": ["overview", "failures", "hosts", "playbooks", "trends"],
                    "description": (
                        "Type of analysis: 'overview' for high-level stats, 'failures' for "
                        "failure patterns, 'hosts' for per-host reliability, 'playbooks' for "
                        "per-playbook stats, 'trends' for recent activity trends"
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Number of recent runs to analyze (default: 100)",
                    "minimum": 10,
                    "maximum": 1000,
                },
                "host_filter": {
                    "type": "string",
                    "description": "Filter analysis to a specific host (optional)",
                },
                "playbook_filter": {
                    "type": "string",
                    "description": "Filter analysis to a specific playbook (optional)",
                },
            },
            "required": [],
        }

    async def execute(
        self,
        analysis_type: str = "overview",
        limit: int = 100,
        host_filter: str = "",
        playbook_filter: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        store = InfrastructureStore.get_instance()
        runs = store.get_run_history(limit=limit)

        if not runs:
            return ToolResult.fail("No run history found. Execute some playbooks first.")

        if playbook_filter:
            runs = [r for r in runs if playbook_filter in r.get("playbook", "")]
        if host_filter:
            runs = [
                r for r in runs
                if host_filter in json.dumps(r.get("hosts", []))
            ]

        if not runs:
            return ToolResult.fail("No matching runs found for the given filters.")

        handler = {
            "overview": self._analyze_overview,
            "failures": self._analyze_failures,
            "hosts": self._analyze_hosts,
            "playbooks": self._analyze_playbooks,
            "trends": self._analyze_trends,
        }.get(analysis_type, self._analyze_overview)

        return handler(runs, store)

    def _analyze_overview(self, runs: list[dict], store: InfrastructureStore) -> ToolResult:
        total = len(runs)
        successful = sum(1 for r in runs if r.get("status") == "successful")
        failed = sum(1 for r in runs if r.get("status") == "failed")
        other = total - successful - failed

        check_runs = sum(1 for r in runs if r.get("mode") == "check")
        apply_runs = sum(1 for r in runs if r.get("mode") == "apply")

        playbooks = set(r.get("playbook", "") for r in runs)
        all_hosts = set()
        for r in runs:
            hosts = r.get("hosts", [])
            if isinstance(hosts, list):
                all_hosts.update(hosts)

        total_events = sum(r.get("event_count", 0) for r in runs)

        drift = store.get_unresolved_drift()

        success_rate = (successful / total * 100) if total else 0

        return ToolResult.ok(
            output=(
                f"Run history overview: {total} runs, {success_rate:.0f}% success rate, "
                f"{len(playbooks)} unique playbook(s), {len(all_hosts)} host(s), "
                f"{len(drift)} unresolved drift item(s)"
            ),
            overview={
                "total_runs": total,
                "successful": successful,
                "failed": failed,
                "other": other,
                "success_rate": round(success_rate, 1),
                "check_runs": check_runs,
                "apply_runs": apply_runs,
                "unique_playbooks": len(playbooks),
                "unique_hosts": len(all_hosts),
                "total_events": total_events,
                "unresolved_drift": len(drift),
            },
        )

    def _analyze_failures(self, runs: list[dict], store: InfrastructureStore) -> ToolResult:
        failed_runs = [r for r in runs if r.get("status") == "failed"]
        if not failed_runs:
            return ToolResult.ok(output="No failures found in the analyzed runs.", failures=[])

        playbook_failures: Counter[str] = Counter()
        host_failures: Counter[str] = Counter()
        recent_failures: list[dict[str, Any]] = []

        for r in failed_runs:
            playbook_failures[r.get("playbook", "unknown")] += 1
            hosts = r.get("hosts", [])
            if isinstance(hosts, list):
                for h in hosts:
                    host_failures[h] += 1

            summary = r.get("summary", {})
            if isinstance(summary, str):
                try:
                    summary = json.loads(summary)
                except json.JSONDecodeError:
                    summary = {}

            recent_failures.append({
                "playbook": r.get("playbook", ""),
                "mode": r.get("mode", ""),
                "hosts": r.get("hosts", []),
                "started_at": r.get("started_at"),
                "event_count": r.get("event_count", 0),
            })

        return ToolResult.ok(
            output=f"{len(failed_runs)} failure(s) found. Top failing playbook: {playbook_failures.most_common(1)[0][0]}",
            failure_count=len(failed_runs),
            top_failing_playbooks=playbook_failures.most_common(10),
            top_failing_hosts=host_failures.most_common(10),
            recent_failures=recent_failures[:20],
        )

    def _analyze_hosts(self, runs: list[dict], store: InfrastructureStore) -> ToolResult:
        host_stats: dict[str, dict[str, int]] = {}

        for r in runs:
            hosts = r.get("hosts", [])
            status = r.get("status", "unknown")
            if isinstance(hosts, list):
                for h in hosts:
                    stats = host_stats.setdefault(h, {"total": 0, "successful": 0, "failed": 0})
                    stats["total"] += 1
                    if status == "successful":
                        stats["successful"] += 1
                    elif status == "failed":
                        stats["failed"] += 1

        for h, stats in host_stats.items():
            stats["success_rate"] = round(
                (stats["successful"] / stats["total"] * 100) if stats["total"] else 0, 1
            )

        sorted_hosts = sorted(
            host_stats.items(),
            key=lambda x: x[1].get("success_rate", 100),
        )

        flaky_hosts = [
            {"host": h, **s}
            for h, s in sorted_hosts
            if s["failed"] > 0
        ]

        return ToolResult.ok(
            output=f"Analyzed {len(host_stats)} host(s). {len(flaky_hosts)} with failures.",
            host_stats=dict(sorted_hosts),
            flaky_hosts=flaky_hosts[:20],
            total_hosts=len(host_stats),
        )

    def _analyze_playbooks(self, runs: list[dict], store: InfrastructureStore) -> ToolResult:
        pb_stats: dict[str, dict[str, Any]] = {}

        for r in runs:
            pb = r.get("playbook", "unknown")
            stats = pb_stats.setdefault(pb, {
                "total": 0, "successful": 0, "failed": 0,
                "check_runs": 0, "apply_runs": 0, "total_events": 0,
            })
            stats["total"] += 1
            stats["total_events"] += r.get("event_count", 0)
            if r.get("status") == "successful":
                stats["successful"] += 1
            elif r.get("status") == "failed":
                stats["failed"] += 1
            if r.get("mode") == "check":
                stats["check_runs"] += 1
            elif r.get("mode") == "apply":
                stats["apply_runs"] += 1

        for stats in pb_stats.values():
            stats["success_rate"] = round(
                (stats["successful"] / stats["total"] * 100) if stats["total"] else 0, 1
            )
            stats["avg_events"] = round(
                stats["total_events"] / stats["total"] if stats["total"] else 0, 1
            )

        sorted_pbs = sorted(pb_stats.items(), key=lambda x: x[1]["total"], reverse=True)

        return ToolResult.ok(
            output=f"Analyzed {len(pb_stats)} unique playbook(s).",
            playbook_stats=dict(sorted_pbs),
            total_playbooks=len(pb_stats),
        )

    def _analyze_trends(self, runs: list[dict], store: InfrastructureStore) -> ToolResult:
        daily: dict[str, dict[str, int]] = {}

        for r in runs:
            ts = r.get("started_at")
            if not ts:
                continue
            day = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            d = daily.setdefault(day, {"total": 0, "successful": 0, "failed": 0})
            d["total"] += 1
            if r.get("status") == "successful":
                d["successful"] += 1
            elif r.get("status") == "failed":
                d["failed"] += 1

        sorted_days = sorted(daily.items())

        if len(sorted_days) >= 2:
            recent = sorted_days[-1][1]
            previous = sorted_days[-2][1]
            trend = "improving" if recent.get("failed", 0) < previous.get("failed", 0) else (
                "declining" if recent.get("failed", 0) > previous.get("failed", 0) else "stable"
            )
        else:
            trend = "insufficient data"

        return ToolResult.ok(
            output=f"Activity trend across {len(sorted_days)} day(s): {trend}",
            daily_stats=dict(sorted_days),
            trend=trend,
            total_days=len(sorted_days),
        )
