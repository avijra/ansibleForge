"""Session reflection — LLM-driven extraction of learnings from completed sessions."""

from __future__ import annotations

import json
from typing import Any

from ansible_forge.knowledge.experience_store import Experience, ExperienceStore
from ansible_forge.logging import get_logger

logger = get_logger(__name__)

REFLECTION_PROMPT = """\
You are reviewing an Ansible automation session. Analyze what happened and extract reusable learnings.

## Session Summary
{session_summary}

## Instructions
Extract 1-5 concrete, reusable learnings from this session. Each learning should be something that would help in a *future* session with a similar goal.

Focus on:
- Module-specific tips or gotchas (e.g. "ansible.builtin.service requires handler flush before checking status")
- OS/distribution-specific patterns (e.g. "On RHEL 9, firewalld zones need explicit reload")
- Error patterns and their fixes
- Effective task ordering or structuring patterns
- Credential/connection patterns that worked

Respond ONLY with a JSON array. Each element must have:
- "trigger": string — when should this learning be recalled (goal description, error pattern, or module name)
- "insight": string — the concrete lesson learned (actionable, specific)
- "context": object — {{"modules": [...], "os": [...], "tags": [...]}}

Example:
[
  {{
    "trigger": "configuring LDAP on RHEL",
    "insight": "Use ansible_password as an extra var, not in inventory, to avoid recursive template errors",
    "context": {{"modules": ["community.general.ldap_attrs"], "os": ["RedHat"], "tags": ["ldap", "credentials"]}}
  }}
]

If there are no meaningful learnings, return an empty array: []
"""


def _summarize_session_events(events: list[dict[str, Any]]) -> str:
    parts: list[str] = []

    user_messages = [
        e["data"].get("content", "")[:200]
        for e in events
        if e["event"] == "user_message" and e["data"].get("content")
    ]
    if user_messages:
        parts.append("User requests:\n" + "\n".join(f"- {m}" for m in user_messages[-5:]))

    tool_calls = []
    for e in events:
        if e["event"] == "tool_call":
            tool = e["data"].get("tool", "?")
            tool_calls.append(tool)
    if tool_calls:
        parts.append(f"Tools used: {', '.join(dict.fromkeys(tool_calls))}")

    tool_results = []
    for e in events:
        if e["event"] == "tool_result":
            tool = e["data"].get("tool", "?")
            status = e["data"].get("status", "?")
            output = e["data"].get("output", "")[:150]
            tool_results.append(f"- {tool}: {status} — {output}")
    if tool_results:
        parts.append("Tool outcomes:\n" + "\n".join(tool_results[-10:]))

    errors = [
        e["data"].get("error", "")[:200]
        for e in events
        if e["event"] == "error_recovery" and e["data"].get("error")
    ]
    if errors:
        parts.append("Errors encountered:\n" + "\n".join(f"- {err}" for err in errors))

    agent_messages = [
        e["data"].get("content", "")[:300]
        for e in events
        if e["event"] == "message" and e["data"].get("content")
    ]
    if agent_messages:
        parts.append(f"Final agent response:\n{agent_messages[-1]}")

    return "\n\n".join(parts) if parts else "No significant events recorded."


def _parse_reflection(content: str) -> list[dict[str, Any]]:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")
        lines = [line for line in lines if not line.startswith("```")]
        content = "\n".join(lines)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("[")
        end = content.rfind("]")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(content[start : end + 1])
            except json.JSONDecodeError:
                logger.warning("reflection_parse_failed", content_preview=content[:200])
                return []
        else:
            return []

    if not isinstance(parsed, list):
        return []

    valid = []
    for item in parsed:
        if isinstance(item, dict) and item.get("trigger") and item.get("insight"):
            valid.append(item)
    return valid


async def reflect_on_session(
    session_id: str,
    events: list[dict[str, Any]],
    llm: Any,
    store: ExperienceStore,
) -> int:
    """Use the LLM to extract learnings from a completed session.

    Returns the number of learnings captured.
    """
    if len(events) < 3:
        return 0

    has_tool_use = any(e["event"] in ("tool_call", "tool_result") for e in events)
    if not has_tool_use:
        return 0

    summary = _summarize_session_events(events)
    prompt = REFLECTION_PROMPT.format(session_summary=summary)

    try:
        response = await llm.complete(
            messages=[
                {"role": "system", "content": "You are an expert Ansible engineer reviewing an automation session for learnings."},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            temperature=0.3,
            max_tokens=2000,
        )
    except Exception:
        logger.warning("reflection_llm_call_failed", session_id=session_id, exc_info=True)
        return 0

    learnings = _parse_reflection(response.content or "")
    saved = 0
    for learning in learnings:
        ctx = learning.get("context", {})
        if not isinstance(ctx, dict):
            ctx = {}
        store.save(Experience(
            type="reflection",
            trigger=str(learning["trigger"])[:500],
            context=ctx,
            solution=str(learning["insight"])[:1000],
            outcome=f"Reflected from session {session_id}",
            confidence=0.4,
            session_id=session_id,
        ))
        saved += 1

    if saved:
        logger.info("reflection_captured", session_id=session_id, count=saved)
    return saved
