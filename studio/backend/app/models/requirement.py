"""
Mark II Studio — RequirementSpec Model
Stores the structured requirements captured during the reverse interview.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class RequirementSpec(Base, TimestampMixin):
    __tablename__ = "requirement_specs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_sessions.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Structured spec
    summary: Mapped[str] = mapped_column(Text, default="")
    requirements_json: Mapped[dict] = mapped_column(
        JSON, default=dict
    )  # Full structured spec: routes, behaviors, security, tech reqs

    # Interview history
    interview_history: Mapped[list] = mapped_column(
        JSON, default=list
    )  # List of {role, content, timestamp} messages

    # Profile-specific fields
    detected_framework: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detected_profile: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    # Architectural Blueprint (Dynamic Profile Logic)
    blueprint_json: Mapped[dict] = mapped_column(
        JSON, default=dict
    )  # Stores {tech_stack, file_tree, install_cmd, startup_cmd, port}

    # Relationships
    session = relationship("ProjectSession", back_populates="requirement_specs")

    def __repr__(self) -> str:
        return f"<RequirementSpec v{self.version} confirmed={self.confirmed}>"
