"""
Mark II Studio — BuildCandidate Model
Represents code produced by a builder (OpenAI or DeepSeek) in a sandbox.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class BuildCandidate(Base, TimestampMixin):
    __tablename__ = "build_candidates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_sessions.id"), nullable=False
    )

    # Builder identity
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # openai | deepseek
    model: Mapped[str] = mapped_column(String(128), nullable=False)

    # Sandbox
    sandbox_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    preview_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    # Build state
    status: Mapped[str] = mapped_column(
        String(32), default="pending"
    )  # pending | building | built | failed

    # Scoring
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_baseline: Mapped[bool] = mapped_column(Boolean, default=False)

    # Artifacts
    files_json: Mapped[dict] = mapped_column(JSON, default=dict)  # {filepath: content}
    build_log: Mapped[str] = mapped_column(Text, default="")
    test_results_json: Mapped[dict] = mapped_column(JSON, default=dict)

    # Patch metadata (for hardening iterations)
    candidate_format: Mapped[str] = mapped_column(String(64), default="generated_source")
    patch_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    operations_count: Mapped[int] = mapped_column(default=0)

    # Relationships
    session = relationship("ProjectSession", back_populates="candidates")

    def __repr__(self) -> str:
        return f"<BuildCandidate {self.provider}/{self.model} score={self.score}>"
