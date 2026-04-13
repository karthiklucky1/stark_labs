"""
Mark II Studio — User Model (GitHub OAuth)
"""
from __future__ import annotations

import uuid

from sqlalchemy import String, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    github_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    github_login: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    avatar_url: Mapped[str] = mapped_column(String(1024), default="")
    access_token: Mapped[str] = mapped_column(String(512), default="")

    # Relationships
    sessions = relationship("ProjectSession", back_populates="user", lazy="selectin")

    def __repr__(self) -> str:
        return f"<User {self.github_login}>"
