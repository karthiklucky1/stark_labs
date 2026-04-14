"""
Mark II Studio — Database Layer
SQLAlchemy async engine, session factory, and declarative Base.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import DateTime, func, inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.settings import settings

# SQLite does not support pool_size / max_overflow
_engine_kwargs: dict = {"echo": False}
if "sqlite" not in settings.database_url:
    _engine_kwargs["pool_size"] = 10
    _engine_kwargs["max_overflow"] = 20
else:
    _engine_kwargs["connect_args"] = {"timeout": 30}

engine = create_async_engine(settings.database_url, **_engine_kwargs)

from sqlalchemy import event

@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Shared declarative base with common columns."""
    pass


class TimestampMixin:
    """Mixin adding created_at / updated_at to any model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        default=lambda: datetime.now(timezone.utc),
    )


async def get_session() -> AsyncSession:  # noqa: F811 — FastAPI dependency
    """FastAPI dependency that yields a DB session."""
    async with async_session_factory() as session:
        try:
            yield session  # type: ignore[misc]
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_tables() -> None:
    """Create all tables (dev convenience — use Alembic in production)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_dev_schema_compatibility)


async def drop_tables() -> None:
    """Drop all tables (dev convenience)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


def _ensure_dev_schema_compatibility(sync_conn) -> None:
    """
    Lightweight dev-only schema compatibility for local SQLite/Postgres usage.
    This keeps existing local DBs usable without a full Alembic setup.
    """
    inspector = inspect(sync_conn)
    tables = set(inspector.get_table_names())

    if "project_sessions" in tables:
        session_columns = {column["name"] for column in inspector.get_columns("project_sessions")}
        if "build_mode" not in session_columns:
            sync_conn.execute(text("ALTER TABLE project_sessions ADD COLUMN build_mode VARCHAR(32) DEFAULT 'balanced'"))
        if "architecture_json" not in session_columns:
            sync_conn.execute(text("ALTER TABLE project_sessions ADD COLUMN architecture_json JSON"))
        sync_conn.execute(text("UPDATE project_sessions SET build_mode = 'balanced' WHERE build_mode IS NULL"))
        sync_conn.execute(text("UPDATE project_sessions SET architecture_json = '{}' WHERE architecture_json IS NULL"))

    if "build_candidates" in tables:
        candidate_columns = {column["name"] for column in inspector.get_columns("build_candidates")}
        if "build_duration_ms" not in candidate_columns:
            sync_conn.execute(text("ALTER TABLE build_candidates ADD COLUMN build_duration_ms FLOAT"))
        if "module_scope_json" not in candidate_columns:
            sync_conn.execute(text("ALTER TABLE build_candidates ADD COLUMN module_scope_json JSON"))
        if "review_notes_json" not in candidate_columns:
            sync_conn.execute(text("ALTER TABLE build_candidates ADD COLUMN review_notes_json JSON"))
        sync_conn.execute(text("UPDATE build_candidates SET module_scope_json = '{}' WHERE module_scope_json IS NULL"))
        sync_conn.execute(text("UPDATE build_candidates SET review_notes_json = '[]' WHERE review_notes_json IS NULL"))
