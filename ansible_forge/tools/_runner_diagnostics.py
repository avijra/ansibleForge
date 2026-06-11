"""Shared helpers for diagnosing ansible-runner failures."""

from __future__ import annotations

import re
from typing import Any

_GENERIC_FALLBACK = "Check the execution log below for details."
_MAX_SNIPPET_CHARS = 1200


def read_runner_stdout(runner_result: Any) -> str:
    stdout = runner_result.stdout
    if hasattr(stdout, "read"):
        raw = stdout.read()
        if hasattr(stdout, "seek"):
            stdout.seek(0)
        if isinstance(raw, bytes):
            return raw.decode(errors="replace")
        return str(raw or "")
    return str(stdout or "")


def _extract_error_snippet(text: str) -> str:
    cleaned = re.sub(r"\x1b\[[0-9;]*m", "", text)
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""

    for line in lines:
        upper = line.upper()
        if line.startswith("ERROR:") or "unsupported locale" in line.lower():
            return line[:_MAX_SNIPPET_CHARS]

    filtered = [
        line
        for line in lines
        if not line.startswith("What's next:")
        and "docker ai" not in line.lower()
        and "gordon" not in line.lower()
    ]
    if not filtered:
        filtered = lines

    snippet = "\n".join(filtered[-8:])
    if len(snippet) > _MAX_SNIPPET_CHARS:
        snippet = snippet[:_MAX_SNIPPET_CHARS] + "…"
    return snippet


def first_task_failure_diagnosis(events: list[dict[str, Any]]) -> str | None:
    for ev in events:
        if ev.get("event") not in ("runner_on_failed", "runner_on_unreachable"):
            continue
        task = ev.get("task", "unknown task")
        host = ev.get("host", "unknown host")
        res = ev.get("result", {})
        msg = res.get("msg") or res.get("stderr") or res.get("module_stderr") or ""
        if isinstance(msg, str) and len(msg) > 300:
            msg = msg[:300] + "…"
        label = "UNREACHABLE" if ev["event"] == "runner_on_unreachable" else "FAILED"
        return f'{label} task "{task}" on {host}: {msg}'
    return None


def diagnose_runner_failure(
    events: list[dict[str, Any]],
    raw_stdout: str = "",
    rc: int | None = None,
) -> str:
    task_diag = first_task_failure_diagnosis(events)
    if task_diag:
        return task_diag

    text = (raw_stdout or "").strip()
    if text:
        snippet = _extract_error_snippet(text)
        if snippet:
            return f"Runner failed before any tasks ran: {snippet}"

    if rc not in (None, 0):
        return f"Runner exited with code {rc}."

    return _GENERIC_FALLBACK
