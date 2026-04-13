"""
Mark II Studio — Pydantic API Schemas for Sessions
Request/response models for the /sessions endpoints.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ── Session ────────────────────────────────────────────────

class SessionCreate(BaseModel):
    intake_mode: str = Field(
        ..., pattern="^(prompt|github|zip|paste)$",
        description="How the user is providing input",
    )
    prompt: Optional[str] = Field(None, description="Initial user prompt (for prompt mode)")
    github_url: Optional[str] = Field(None, description="GitHub repo URL (for github mode)")


class ShowcaseMini(BaseModel):
    title: str
    is_public: bool

    model_config = {"from_attributes": True}


class SessionResponse(BaseModel):
    id: uuid.UUID
    intake_mode: str
    profile_type: Optional[str]
    preview_mode: Optional[str] = None
    status: str
    github_repo_url: Optional[str]
    original_prompt: Optional[str]
    created_at: datetime
    updated_at: datetime
    showcase: Optional[ShowcaseMini] = None

    model_config = {"from_attributes": True}


class SessionDetail(SessionResponse):
    requirements: list[RequirementSpecResponse] = Field(default_factory=list)
    candidates: list[CandidateResponse] = Field(default_factory=list)
    mark_runs: list[MarkRunResponse] = Field(default_factory=list)
    judge_decisions: list[JudgeDecisionResponse] = Field(default_factory=list)
    change_requests: list[ChangeRequestResponse] = Field(default_factory=list)


# ── Intake ─────────────────────────────────────────────────

class IntakePayload(BaseModel):
    """For code intake — paste mode sends content directly."""
    files: Optional[dict[str, str]] = Field(None, description="Filename → content map for paste mode")
    github_url: Optional[str] = Field(None, description="GitHub repo URL")


# ── Interview ──────────────────────────────────────────────

class InterviewAnswer(BaseModel):
    message: str = Field(..., min_length=1, description="User's answer to the interview question")


class InterviewMessage(BaseModel):
    role: str  # "assistant" (Claude) or "user"
    content: str
    timestamp: Optional[datetime] = None


# ── Requirement Spec ───────────────────────────────────────

class RequirementSpecResponse(BaseModel):
    id: uuid.UUID
    version: int
    confirmed: bool
    summary: str
    requirements_json: dict
    detected_framework: Optional[str]
    detected_profile: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class RequirementConfirm(BaseModel):
    confirmed: bool = True


# ── Build Candidate ────────────────────────────────────────

class CandidateResponse(BaseModel):
    id: uuid.UUID
    provider: str
    model: str
    status: str
    score: Optional[float]
    is_baseline: bool
    preview_url: Optional[str]
    build_log: str
    candidate_format: str
    patch_summary: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Change Request ─────────────────────────────────────────

class CommentSubmit(BaseModel):
    comment: str = Field(..., min_length=1, description="User's mid-build comment")


class PreviewRequest(BaseModel):
    path: str = Field("/", min_length=1)
    method: str = Field("GET", min_length=1)


class ChangeRequestResponse(BaseModel):
    id: uuid.UUID
    user_comment: str
    classification: str
    structured_instruction: dict
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Judge Decision ─────────────────────────────────────────

class JudgeDecisionResponse(BaseModel):
    id: uuid.UUID
    winning_candidate_id: Optional[uuid.UUID]
    reasoning: str
    scores_json: dict
    criteria_json: list
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Mark Run ───────────────────────────────────────────────

class MarkRunResponse(BaseModel):
    id: uuid.UUID
    mark_number: int
    mark_name: str
    passed: bool
    failure_type: Optional[str]
    swarm_report_json: dict
    patch_summary: Optional[str]
    repair_provider: Optional[str]
    score: Optional[float]
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Forward references ─────────────────────────────────────
# Pydantic v2 needs model_rebuild for forward refs
SessionDetail.model_rebuild()
