"""
Mark II Studio — ProjectSession Model
Central entity representing a user's build session.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class ProjectSession(Base, TimestampMixin):
    __tablename__ = "project_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Intake
    intake_mode: Mapped[str] = mapped_column(
        String(32), default="prompt"
    )  # prompt | github | zip | paste

    # Profile detection
    profile_type: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )  # fastapi_service | nextjs_webapp | None (unsupported)

    # Session state machine
    status: Mapped[str] = mapped_column(
        String(32), default="created"
    )  # created | interviewing | spec_review | building | judging | hardening | complete | failed

    # Intake metadata
    github_repo_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    original_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    intake_files_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    user = relationship("User", back_populates="sessions", lazy="selectin")
    requirement_specs = relationship(
        "RequirementSpec", back_populates="session", lazy="selectin",
        order_by="RequirementSpec.version",
    )
    candidates = relationship(
        "BuildCandidate", back_populates="session", lazy="selectin",
    )
    change_requests = relationship(
        "ChangeRequest", back_populates="session", lazy="selectin",
        order_by="ChangeRequest.created_at",
    )
    judge_decisions = relationship(
        "JudgeDecision", back_populates="session", lazy="selectin",
    )
    mark_runs = relationship(
        "MarkRun", back_populates="session", lazy="selectin",
        order_by="MarkRun.mark_number",
    )
    showcase = relationship(
        "SessionShowcase", back_populates="session", lazy="selectin",
        uselist=False, cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ProjectSession {self.id} status={self.status}>"
