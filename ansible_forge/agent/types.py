"""Shared types for the agent subsystem."""

from __future__ import annotations

from enum import Enum


class SessionStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ERROR = "error"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_SECRET = "awaiting_secret"
    REJECTED = "rejected"
    MAX_STEPS_REACHED = "max_steps_reached"
