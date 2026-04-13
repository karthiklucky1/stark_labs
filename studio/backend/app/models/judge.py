"""
Mark II Studio — JudgeDecision Model
Stores Claude's structured judgment comparing build candidates.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class JudgeDecision(Base, TimestampMixin):
    __tablename__ = "judge_decisions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_sessions.id"), nullable=False
    )
    winning_candidate_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("build_candidates.id"), nullable=True
    )

    # Judge output
    reasoning: Mapped[str] = mapped_column(Text, default="")
    scores_json: Mapped[dict] = mapped_column(
        JSON, default=dict
    )  # {candidate_id: {criterion: score}}
    criteria_json: Mapped[list] = mapped_column(
        JSON, default=list
    )  # List of evaluation criteria used

    # Relationships
    session = relationship("ProjectSession", back_populates="judge_decisions")
    winning_candidate = relationship("BuildCandidate", lazy="selectin")

    def __repr__(self) -> str:
        return f"<JudgeDecision winner={self.winning_candidate_id}>"
