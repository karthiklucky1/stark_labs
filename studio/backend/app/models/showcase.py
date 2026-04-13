"""
Mark II Studio — SessionShowcase Model
Stores autonomous marketing narratives and interactive demo scripts.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class SessionShowcase(Base, TimestampMixin):
    __tablename__ = "session_showcases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_sessions.id"), nullable=False
    )

    # The Chronicle - AI generated narrative
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    marketing_pitch: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Showcase Assets
    hero_image_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    
    # Interaction Script - A sequence of actions the frontend can execute
    # Format: [{"action": "click", "selector": "#start", "caption": "Initiating sequence...", "delay": 2000}]
    demo_script_json: Mapped[dict] = mapped_column(JSON, default=list)

    # Stats & Meta
    telemetry_highlights_json: Mapped[dict] = mapped_column(JSON, default=dict)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    view_count: Mapped[int] = mapped_column(default=0)

    # Relationships
    session = relationship("ProjectSession", back_populates="showcase")

    def __repr__(self) -> str:
        return f"<SessionShowcase {self.title} session={self.session_id}>"
