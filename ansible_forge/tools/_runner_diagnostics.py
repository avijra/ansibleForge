"""Shared helpers for diagnosing ansible-runner failures."""

from __future__ import annotations

import re
from typing import Any

GENERIC_FALLBACK = "Check the execution log below for details."
_GENERIC_FALLBACK = GENERIC_FALLBACK
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


_ARCH_MISMATCH_SIGNATURES = (
    "lfstack.push",
    "exec format error",
    "cannot execute binary file",
    "wrong architecture",
)

_ARCH_MISMATCH_HINT_BASE = (
    " Likely architecture mismatch: a binary built for a different CPU "
    "architecture is running inside the EE container."
)


def _arch_mismatch_hint() -> str:
    try:
        from ansible_forge.tools.ee_runtime import detect_ee_platform

        platform = detect_ee_platform()
    except Exception:
        platform = None
    if platform:
        return (
            f"{_ARCH_MISMATCH_HINT_BASE} The EE is {platform['raw']} — download "
            f"the {platform['os']} build for {platform['arch']}."
        )
    return (
        f"{_ARCH_MISMATCH_HINT_BASE} Download the binary that matches the EE "
        "architecture (e.g. arm64/aarch64 on Apple Silicon)."
    )


def _task_failure_text(events: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for ev in events:
        if ev.get("event") not in ("runner_on_failed", "runner_on_unreachable"):
            continue
        res = ev.get("result", {})
        if not isinstance(res, dict):
            continue
        for key in ("msg", "stderr", "module_stderr", "stdout", "module_stdout"):
            value = res.get(key)
            if isinstance(value, str) and value:
                parts.append(value)
    return "\n".join(parts)


def _first_failure_parts(events: list[dict[str, Any]]) -> tuple[str, str] | None:
    for ev in events:
        if ev.get("event") not in ("runner_on_failed", "runner_on_unreachable"):
            continue
        task = ev.get("task", "unknown task")
        host = ev.get("host", "unknown host")
        res = ev.get("result", {})
        if isinstance(res, dict):
            msg = (
                res.get("msg")
                or res.get("stderr")
                or res.get("module_stderr")
                or res.get("reason")
                or res.get("exception")
                or ""
            )
        else:
            msg = ""
        if isinstance(msg, str) and len(msg) > 300:
            msg = msg[:300] + "…"
        label = "UNREACHABLE" if ev["event"] == "runner_on_unreachable" else "FAILED"
        return f'{label} task "{task}" on {host}:', str(msg).strip()
    return None


def first_task_failure_diagnosis(events: list[dict[str, Any]]) -> str | None:
    parts = _first_failure_parts(events)
    if parts is None:
        return None
    prefix, msg = parts
    return f"{prefix} {msg}".strip()


def diagnose_runner_failure(
    events: list[dict[str, Any]],
    raw_stdout: str = "",
    rc: int | None = None,
) -> str:
    parts = _first_failure_parts(events)
    haystack = ((raw_stdout or "") + "\n" + _task_failure_text(events)).lower()
    if any(sig in haystack for sig in _ARCH_MISMATCH_SIGNATURES):
        prefix = f"{parts[0]} {parts[1]}".strip() if parts else "Runner failed."
        return prefix + _arch_mismatch_hint()

    text = (raw_stdout or "").strip()
    snippet = _extract_error_snippet(text) if text else ""

    if parts is not None:
        prefix, msg = parts
        if msg:
            return f"{prefix} {msg}".strip()
        if snippet:
            return f"{prefix} {snippet}".strip()
        return prefix

    if snippet:
        return f"Runner failed before any tasks ran: {snippet}"

    if rc not in (None, 0):
        return f"Runner exited with code {rc}."

    return _GENERIC_FALLBACK
