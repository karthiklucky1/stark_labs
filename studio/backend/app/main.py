"""
Mark II Studio — FastAPI Application Entrypoint
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.sessions import router as sessions_router
from app.api.codex import router as codex_router
from app.database import create_tables
from app.settings import settings

# Import models to ensure they are registered with Base.metadata for the startup create_tables
import app.models.session 
import app.models.requirement
import app.models.candidate
import app.models.showcase
import app.models.mark_run
import app.models.change_request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown hooks."""
    logger.info("🚀 %s starting up...", settings.product_name)

    # Create database tables (dev convenience — use Alembic in production)
    try:
        await create_tables()
        logger.info("✅ Database tables ready")
    except Exception as e:
        logger.warning("⚠️  Database not available: %s (running without persistence)", e)

    logger.info("✅ %s is ready", settings.product_name)
    yield

    # Shutdown
    logger.info("👋 %s shutting down...", settings.product_name)


app = FastAPI(
    title=settings.product_name,
    description=(
        "Team-facing build-break-heal platform. "
        "Submit a prompt or code, get a reverse interview from Claude, "
        "watch OpenAI + DeepSeek build in parallel, "
        "then harden via the Mark II adversarial loop."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(sessions_router)
app.include_router(codex_router)


@app.get("/")
async def root():
    return {
        "name": settings.product_name,
        "version": "1.0.0",
        "status": "operational",
        "docs": "/docs",
        "supported_profiles": settings.supported_profiles,
    }
