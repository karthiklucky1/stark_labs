"""
Mark II Studio — MarkRun Model
Tracks each iteration of the hardening loop (Mark I through VII).
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class MarkRun(Base, TimestampMixin):
    __tablename__ = "mark_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_sessions.id"), nullable=False
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("build_candidates.id"), nullable=False
    )

    # Mark identity
    mark_number: Mapped[int] = mapped_column(Integer, nullable=False)
    mark_name: Mapped[str] = mapped_column(String(16), nullable=False)  # I, II, III...

    # Result
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    failure_type: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Swarm attack report
    swarm_report_json: Mapped[dict] = mapped_column(JSON, default=dict)

    # Repair info
    patch_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    repair_provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    repair_model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    score: Mapped[Optional[float]] = mapped_column(nullable=True)

    # Relationships
    session = relationship("ProjectSession", back_populates="mark_runs")
    candidate = relationship("BuildCandidate", lazy="selectin")

    def __repr__(self) -> str:
        return f"<MarkRun {self.mark_name} passed={self.passed}>"
