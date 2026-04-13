"""
Mark II Studio — SSE Event Types
Typed event models for the Server-Sent Events stream.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """Base class for all SSE events."""
    event_type: str
    session_id: uuid.UUID
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
    data: dict[str, Any] = Field(default_factory=dict)


class InterviewMessageEvent(BaseEvent):
    event_type: str = "interview_message"
    # data: {role, content}


class BuildProgressEvent(BaseEvent):
    event_type: str = "build_progress"
    # data: {provider, status, detail}


class CandidateReadyEvent(BaseEvent):
    event_type: str = "candidate_ready"
    # data: {candidate_id, provider, score, preview_url}


class JudgeResultEvent(BaseEvent):
    event_type: str = "judge_result"
    # data: {winning_candidate_id, reasoning, scores}


class MarkStartedEvent(BaseEvent):
    event_type: str = "mark_started"
    # data: {mark_number, mark_name}


class MarkResultEvent(BaseEvent):
    event_type: str = "mark_result"
    # data: {mark_number, mark_name, passed, failure_type}


class PreviewUpdateEvent(BaseEvent):
    event_type: str = "preview_update"
    # data: {preview_url, status}


class ChangeRequestEvent(BaseEvent):
    event_type: str = "change_request"
    # data: {classification, instruction, status}


class DeliveryReadyEvent(BaseEvent):
    event_type: str = "delivery_ready"
    # data: {artifact_url, report_url}


class SessionStatusEvent(BaseEvent):
    event_type: str = "session_status"
    # data: {status, detail}


class ErrorEvent(BaseEvent):
    event_type: str = "error"
    # data: {error, detail}
