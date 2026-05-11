"""Periodic consolidation — LLM generalizes repeated experiences into rules."""

from __future__ import annotations

import json
from typing import Any

from ansible_forge.knowledge.experience_store import Experience, ExperienceStore
from ansible_forge.logging import get_logger

logger = get_logger(__name__)

CONSOLIDATION_PROMPT = """\
You are an expert Ansible engineer. Below are {count} similar experiences from past automation sessions, grouped by type.

## Experiences
{experiences}

## Instructions
Review these experiences and extract 1-3 generalized rules that would be useful for *any* future session encountering similar situations.

A rule should:
- Be specific and actionable (not generic advice)
- Be supported by at least 2 of the experiences above
- Include when it applies (trigger condition)

Respond ONLY with a JSON array. Each element must have:
- "trigger": string — when should this rule be applied (module name, error pattern, or goal type)
- "rule": string — the concrete, generalized rule
- "context": object — {{"modules": [...], "os": [...], "tags": [...]}}
- "supporting_count": number — how many experiences support this rule

Example:
[
  {{
    "trigger": "using ansible.builtin.service on RHEL",
    "rule": "Always flush handlers before checking service status, because handlers run at end of play by default",
    "context": {{"modules": ["ansible.builtin.service"], "os": ["RedHat"], "tags": ["handlers"]}},
    "supporting_count": 3
  }}
]

If no meaningful rules can be derived, return an empty array: []
"""


def _format_experiences_for_consolidation(experiences: list[Experience]) -> str:
    lines: list[str] = []
    for i, exp in enumerate(experiences[:15], 1):
        lines.append(
            f"{i}. [{exp.type}] trigger='{exp.trigger[:200]}' "
            f"solution='{exp.solution[:300]}' outcome='{exp.outcome[:100]}'"
        )
    return "\n".join(lines)


def _parse_consolidation(content: str) -> list[dict[str, Any]]:
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
                logger.warning("consolidation_parse_failed", content_preview=content[:200])
                return []
        else:
            return []

    if not isinstance(parsed, list):
        return []

    valid = []
    for item in parsed:
        if isinstance(item, dict) and item.get("trigger") and item.get("rule"):
            valid.append(item)
    return valid


async def consolidate_experiences(
    store: ExperienceStore,
    llm: Any,
) -> int:
    """Review accumulated experiences and generalize into rules.

    Returns the number of new rules created.
    """
    groups = await store.aget_all_by_type_grouped(min_group_size=3)
    if not groups:
        logger.info("consolidation_skipped", reason="not enough experiences")
        return 0

    all_experiences: list[Experience] = []
    for exps in groups.values():
        all_experiences.extend(exps)

    if not all_experiences:
        return 0

    formatted = _format_experiences_for_consolidation(all_experiences)
    prompt = CONSOLIDATION_PROMPT.format(
        count=len(all_experiences),
        experiences=formatted,
    )

    try:
        response = await llm.complete(
            messages=[
                {"role": "system", "content": "You are an expert Ansible engineer generalizing learnings into reusable rules."},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            temperature=0.2,
            max_tokens=2000,
        )
    except Exception:
        logger.warning("consolidation_llm_call_failed", exc_info=True)
        return 0

    rules = _parse_consolidation(response.content or "")
    saved = 0
    skipped = 0
    for rule_data in rules:
        ctx = rule_data.get("context", {})
        if not isinstance(ctx, dict):
            ctx = {}
        trigger = str(rule_data["trigger"])[:500]
        solution = str(rule_data["rule"])[:1000]
        supporting = rule_data.get("supporting_count", 2)
        confidence = min(0.5 + (supporting * 0.1), 0.95)

        existing = store.find_similar("rule", trigger, solution, threshold=0.5)
        if existing:
            if confidence > existing.confidence:
                existing.solution = solution
                existing.confidence = confidence
                existing.trigger = trigger
                await store.asave(existing)
                saved += 1
            else:
                skipped += 1
            continue

        await store.asave(Experience(
            type="rule",
            trigger=trigger,
            context=ctx,
            solution=solution,
            outcome=f"Consolidated from {supporting} experiences",
            confidence=confidence,
        ))
        saved += 1

    if saved or skipped:
        logger.info("consolidation_complete", rules_created=saved, duplicates_skipped=skipped)
    return saved
