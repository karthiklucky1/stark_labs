"""
Mark II Studio — Codex Model
Stores harvested evolution patterns: Broken Code -> Attack -> Patch.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class CodexPattern(Base, TimestampMixin):
    __tablename__ = "codex_patterns"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_sessions.id"), nullable=False
    )
    mark_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mark_runs.id"), nullable=False
    )

    # Evolution Data
    vulnerability_type: Mapped[str] = mapped_column(String(256), nullable=False)
    attack_payload: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Code Files before and after
    # Stored as JSON { filename: content }
    broken_code_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    fixed_code_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    
    # Metadata for training
    language: Mapped[str] = mapped_column(String(32), default="python")
    framework: Mapped[str] = mapped_column(String(64), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<CodexPattern {self.vulnerability_type} id={self.id}>"
