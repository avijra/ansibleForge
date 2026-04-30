"""Tests for the async approval gate."""

from __future__ import annotations

import asyncio

import pytest

from ansible_forge.safety.approval import ApprovalGate, ApprovalRequest, ApprovalStatus


@pytest.fixture
def gate() -> ApprovalGate:
    return ApprovalGate()


def test_create_request(gate: ApprovalGate) -> None:
    req = gate.create_request("sess-1", "Deploy", "paths: foo.yml")

    assert req.session_id == "sess-1"
    assert req.description == "Deploy"
    assert req.diff_summary == "paths: foo.yml"
    assert req.status == ApprovalStatus.PENDING
    assert gate.get_request("sess-1") is req


def test_approve(gate: ApprovalGate) -> None:
    gate.create_request("s1", "d", "")
    gate.approve("s1")

    req = gate.get_request("s1")
    assert req is not None
    assert req.status == ApprovalStatus.APPROVED


async def test_wait_after_approve_returns_approved(gate: ApprovalGate) -> None:
    req = gate.create_request("s1", "d", "")
    gate.approve("s1")
    status = await req.wait()
    assert status == ApprovalStatus.APPROVED


def test_reject_with_feedback(gate: ApprovalGate) -> None:
    gate.create_request("s1", "d", "")
    ok = gate.reject("s1", "needs rollback plan")

    assert ok is True
    req = gate.get_request("s1")
    assert req is not None
    assert req.status == ApprovalStatus.REJECTED
    assert req.feedback == "needs rollback plan"


async def test_wait_after_reject(gate: ApprovalGate) -> None:
    req = gate.create_request("s1", "d", "")
    gate.reject("s1", "no")

    status = await req.wait()
    assert status == ApprovalStatus.REJECTED


async def test_wait_timeout_sets_expired(gate: ApprovalGate) -> None:
    req = gate.create_request("s1", "d", "")
    status = await req.wait(timeout=0.05)

    assert status == ApprovalStatus.EXPIRED
    assert req.status == ApprovalStatus.EXPIRED


def test_cleanup_removes_pending(gate: ApprovalGate) -> None:
    gate.create_request("s1", "d", "")
    gate.cleanup("s1")

    assert gate.get_request("s1") is None


def test_approve_non_pending_returns_false(gate: ApprovalGate) -> None:
    gate.create_request("s1", "d", "")
    gate.reject("s1")

    assert gate.approve("s1") is False


def test_reject_twice_returns_false_second_time(gate: ApprovalGate) -> None:
    gate.create_request("s1", "d", "")
    assert gate.reject("s1") is True
    assert gate.reject("s1", "again") is False


async def test_approval_request_wait_unblocks_when_approve_called_async(
    gate: ApprovalGate,
) -> None:
    req = ApprovalRequest("s2", "", "")

    async def approve_later() -> None:
        await asyncio.sleep(0.01)
        req.approve()

    t = asyncio.create_task(approve_later())
    status = await req.wait(timeout=1.0)
    await t
    assert status == ApprovalStatus.APPROVED
