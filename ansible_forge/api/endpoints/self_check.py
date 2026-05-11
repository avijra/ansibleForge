"""Self-check API endpoint for runtime environment validation."""

from __future__ import annotations

from fastapi import APIRouter

from ansible_forge.self_check import run_self_check

router = APIRouter()


@router.get("/self-check")
async def get_self_check() -> dict:
    """Run environment validation and return the report.

    Returns a structured report of all checks with pass/fail status.
    Used by the desktop app on first launch and for manual diagnostics.
    """
    report = await run_self_check()
    return report.to_dict()
