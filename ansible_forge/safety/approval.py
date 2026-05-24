"""Async approval gate for gating playbook execution behind human approval."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalRequest:
    def __init__(
        self,
        session_id: str,
        description: str,
        diff_summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.session_id = session_id
        self.description = description
        self.diff_summary = diff_summary
        self.metadata = metadata or {}
        self.status = ApprovalStatus.PENDING
        self.feedback: str = ""
        self._event = asyncio.Event()

    def approve(self, response_data: dict[str, Any] | None = None) -> None:
        self.status = ApprovalStatus.APPROVED
        self.response_data = response_data or {}
        self._event.set()

    def reject(self, feedback: str = "") -> None:
        self.status = ApprovalStatus.REJECTED
        self.feedback = feedback
        self._event.set()

    async def wait(self, timeout: float | None = None) -> ApprovalStatus:
        """Block until the request is approved/rejected or timeout expires."""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except TimeoutError:
            self.status = ApprovalStatus.EXPIRED
        return self.status


class ApprovalGate:
    """Manages pending approval requests indexed by session ID."""

    def __init__(self) -> None:
        self._pending: dict[str, ApprovalRequest] = {}

    def create_request(
        self,
        session_id: str,
        description: str,
        diff_summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        req = ApprovalRequest(
            session_id=session_id,
            description=description,
            diff_summary=diff_summary,
            metadata=metadata,
        )
        self._pending[session_id] = req
        logger.info("approval_requested", session_id=session_id)
        return req

    def get_request(self, session_id: str) -> ApprovalRequest | None:
        return self._pending.get(session_id)

    def approve(self, session_id: str, response_data: dict[str, Any] | None = None) -> bool:
        req = self._pending.get(session_id)
        if req and req.status == ApprovalStatus.PENDING:
            req.approve(response_data)
            logger.info("approval_granted", session_id=session_id)
            return True
        return False

    def reject(self, session_id: str, feedback: str = "") -> bool:
        req = self._pending.get(session_id)
        if req and req.status == ApprovalStatus.PENDING:
            req.reject(feedback)
            logger.info("approval_rejected", session_id=session_id)
            return True
        return False

    def cleanup(self, session_id: str) -> None:
        req = self._pending.pop(session_id, None)
        if req and req.status == ApprovalStatus.PENDING:
            req.status = ApprovalStatus.EXPIRED
            req._event.set()
