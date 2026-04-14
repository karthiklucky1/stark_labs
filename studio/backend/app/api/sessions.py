"""
Mark II Studio — Session API Routes
All /sessions endpoints for the build pipeline.
"""
from __future__ import annotations

import json
import logging
import time
import uuid

logger = logging.getLogger(__name__)

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory, get_session
from app.events.bus import event_bus
from app.models.session import ProjectSession
from app.models.requirement import RequirementSpec
from app.models.candidate import BuildCandidate
from app.models.change_request import ChangeRequest
from app.models.mark_run import MarkRun
from app.schemas.session import (
    ChangeRequestResponse,
    CommentSubmit,
    IntakePayload,
    InterviewAnswer,
    PreviewRequest,
    RequirementConfirm,
    RequirementSpecResponse,
    SessionCreate,
    SessionResponse,
)
from app.schemas.showcase import ShowcaseResponse
from app.schemas.events import ChangeRequestEvent, PreviewUpdateEvent, SessionStatusEvent
from app.services.orchestrator import orchestrator
from app.services.nextjs_repair import repair_nextjs_project_files
from app.services.profiles import detect_profile, get_profile
from app.services.sandbox import sandbox_manager
from app.services.showcase import showcase_service
from app.settings import settings

router = APIRouter(prefix="/sessions", tags=["sessions"])

# Tracks session IDs currently running a build or hardening task (in-process guard)
_active_tasks: set[uuid.UUID] = set()
_active_preview_repairs: set[uuid.UUID] = set()
_preview_repair_backoff_until: dict[uuid.UUID, float] = {}
_preview_failure_counts: dict[uuid.UUID, int] = {}
_PREVIEW_REPAIR_COOLDOWN_S = 45.0
_PREVIEW_FAILURE_THRESHOLD = 2
_INCONCLUSIVE_MARKERS = (
    "request failed",
    "probe synthesis failed",
    "judge unavailable",
    "judge error",
    "readtimeout",
    "timed out",
    "does not show",
    "not evidence",
    "no confirmed security bypass",
    "normal page load",
    "generic html",
    "app shell",
)


async def _run_and_clear(coro_fn, session_id: uuid.UUID) -> None:
    """Run an orchestrator coroutine and remove the session from the active-task guard when done."""
    try:
        await coro_fn(session_id)
    finally:
        _active_tasks.discard(session_id)


def _queue_session_task_once(background_tasks: BackgroundTasks, session_id: uuid.UUID, coro_fn) -> bool:
    """Schedule a session task only once per process."""
    if session_id in _active_tasks:
        return False
    _active_tasks.add(session_id)
    background_tasks.add_task(_run_and_clear, coro_fn, session_id)
    return True


# ── Helpers ────────────────────────────────────────────────

async def _get_session_or_404(
    session_id: uuid.UUID, db: AsyncSession
) -> ProjectSession:
    result = await db.execute(
        select(ProjectSession).where(ProjectSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _resolve_preview_runtime(
    session: ProjectSession,
    spec: RequirementSpec | None,
    files: dict[str, str] | None,
) -> tuple[str, str]:
    files = files or {}
    profile = get_profile(
        session.profile_type or "unsupported",
        blueprint=spec.blueprint_json if spec else None,
    )
    startup_cmd = profile.startup_command
    smoke_config = profile.get_smoke_test_config()
    preview_mode = profile.preview_mode
    health_path = smoke_config.get("health_endpoint", "/health") or "/health"
    page_path = smoke_config.get("page_endpoint", "/") or "/"

    if files and (not startup_cmd or profile.name in {"dynamic_profile", "unsupported"}):
        detected = detect_profile(files)
        if detected.name != "unsupported":
            startup_cmd = detected.startup_command
            detected_smoke_config = detected.get_smoke_test_config()
            preview_mode = detected.preview_mode
            if profile.name == "unsupported":
                health_path = detected_smoke_config.get("health_endpoint", health_path) or health_path
                page_path = detected_smoke_config.get("page_endpoint", page_path) or page_path

    probe_path = page_path if preview_mode == "iframe" else health_path
    return startup_cmd, probe_path


def _resolve_preview_mode(
    session: ProjectSession,
    spec: RequirementSpec | None,
    files: dict[str, str] | None,
) -> str | None:
    files = files or {}
    profile = get_profile(
        session.profile_type or "unsupported",
        blueprint=spec.blueprint_json if spec else None,
    )
    preview_mode = profile.preview_mode

    if files and profile.name in {"dynamic_profile", "unsupported"}:
        detected = detect_profile(files)
        if detected.name != "unsupported":
            preview_mode = detected.preview_mode

    return preview_mode


def _session_response(
    session: ProjectSession,
    *,
    preview_mode: str | None = None,
) -> SessionResponse:
    response = SessionResponse.model_validate(session)
    return response.model_copy(
        update={
            "preview_mode": preview_mode,
            "planned_builders": orchestrator.get_planned_builders(session.build_mode),
        }
    )


def _normalize_preview_path(path: str) -> str:
    normalized = (path or "/").strip()
    if not normalized:
        normalized = "/"
    if "://" in normalized or normalized.startswith("//"):
        raise HTTPException(status_code=400, detail="Preview path must be relative")
    if not normalized.startswith("/"):
        normalized = f"/{normalized}"
    return normalized


def _derive_mark_result_type(mark_run: MarkRun) -> str:
    if mark_run.passed:
        return "passed"

    summary = (mark_run.swarm_report_json or {}).get("summary") or {}
    stored = summary.get("result_type")
    if stored in {"passed", "breach", "inconclusive"}:
        return str(stored)

    phases = (mark_run.swarm_report_json or {}).get("phases") or []
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        outcome = str(((phase.get("metrics") or {}).get("outcome")) or "").lower()
        if outcome in {"execution_failed", "judge_unavailable", "probe_synthesis_failed", "inconclusive"}:
            return "inconclusive"

    joined = f"{mark_run.failure_type or ''}\n{mark_run.rejection_reason or ''}".lower()
    if (mark_run.failure_type or "") == "AttackExecutionFailure":
        return "inconclusive"
    if any(marker in joined for marker in _INCONCLUSIVE_MARKERS):
        return "inconclusive"
    return "breach"


async def _resolve_preview_state(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
) -> dict[str, str | None]:
    session = await _get_session_or_404(session_id, db)

    result = await db.execute(
        select(BuildCandidate)
        .where(BuildCandidate.session_id == session_id)
        .where(BuildCandidate.is_baseline == True)
    )
    baseline = result.scalar_one_or_none()

    if not baseline:
        return {"session_id": str(session_id), "preview_url": None, "status": "unavailable"}

    if session.status == "hardening":
        return {
            "session_id": str(session_id),
            "preview_url": baseline.preview_url,
            "status": "paused",
            "detail": "Preview is temporarily paused while hardening reuses the sandbox",
        }

    is_alive = await sandbox_manager.is_sandbox_alive(baseline.sandbox_id)
    if not is_alive:
        background_tasks.add_task(orchestrator.restart_sandbox, session_id)
        return {
            "session_id": str(session_id),
            "preview_url": baseline.preview_url,
            "status": "restoring",
            "detail": "Sandbox expired, initiating autonomous recovery",
        }

    result = await db.execute(
        select(RequirementSpec)
        .where(RequirementSpec.session_id == session_id)
        .where(RequirementSpec.confirmed == True)
        .order_by(RequirementSpec.version.desc())
    )
    spec = result.scalar_one_or_none()

    repair_files, files_changed = repair_nextjs_project_files(baseline.files_json or {})
    if files_changed:
        background_tasks.add_task(_restart_preview_process, session_id)
        return {
            "session_id": str(session_id),
            "preview_url": baseline.preview_url,
            "status": "restoring",
            "detail": "Repairing generated Next.js project files and restarting preview",
        }

    startup_cmd, health_path = _resolve_preview_runtime(
        session,
        spec,
        repair_files,
    )
    canonical_preview_url = await sandbox_manager.get_service_url_for_command(
        baseline.sandbox_id,
        startup_cmd,
        health_path=health_path,
        files=repair_files,
    )
    effective_preview_url = canonical_preview_url or baseline.preview_url

    if not await sandbox_manager.is_service_available(effective_preview_url, health_path=health_path):
        now = time.monotonic()
        failures = _preview_failure_counts.get(session_id, 0) + 1
        _preview_failure_counts[session_id] = failures
        if (
            failures >= _PREVIEW_FAILURE_THRESHOLD
            and
            session_id not in _active_preview_repairs
            and now >= _preview_repair_backoff_until.get(session_id, 0.0)
        ):
            _preview_repair_backoff_until[session_id] = now + _PREVIEW_REPAIR_COOLDOWN_S
            background_tasks.add_task(_restart_preview_process, session_id)
        return {
            "session_id": str(session_id),
            "preview_url": effective_preview_url,
            "status": "restoring",
            "detail": "Preview process not responding, restarting service",
        }

    _preview_failure_counts.pop(session_id, None)
    _preview_repair_backoff_until.pop(session_id, None)
    return {
        "session_id": str(session_id),
        "preview_url": effective_preview_url,
        "status": "active",
    }


async def _restart_preview_process(session_id: uuid.UUID) -> None:
    if session_id in _active_preview_repairs:
        return

    _active_preview_repairs.add(session_id)
    try:
        async with async_session_factory() as db:
            session_result = await db.execute(
                select(ProjectSession).where(ProjectSession.id == session_id)
            )
            session = session_result.scalar_one_or_none()
            if session is None:
                return

            baseline_result = await db.execute(
                select(BuildCandidate)
                .where(BuildCandidate.session_id == session_id)
                .where(BuildCandidate.is_baseline == True)
            )
            baseline = baseline_result.scalar_one_or_none()
            if baseline is None or not baseline.sandbox_id:
                return

            spec_result = await db.execute(
                select(RequirementSpec)
                .where(RequirementSpec.session_id == session_id)
                .where(RequirementSpec.confirmed == True)
                .order_by(RequirementSpec.version.desc())
            )
            spec = spec_result.scalar_one_or_none()

            repair_files, files_changed = repair_nextjs_project_files(baseline.files_json or {})
            if files_changed:
                baseline.files_json = repair_files

            startup_cmd, health_path = _resolve_preview_runtime(
                session,
                spec,
                repair_files,
            )
            if not startup_cmd:
                logger.warning("No startup command available to repair preview for session %s", session_id)
                return

            try:
                await sandbox_manager.upload_files(baseline.sandbox_id, repair_files)
                new_url = await sandbox_manager.start_preview(
                    baseline.sandbox_id,
                    startup_cmd,
                    health_path=health_path,
                )
            except Exception as exc:
                logger.error("Preview restart failed in-place for session %s: %s", session_id, exc)
                await orchestrator.restart_sandbox(session_id)
                return

            baseline.preview_url = new_url
            await db.commit()

        await event_bus.publish(PreviewUpdateEvent(
            session_id=session_id,
            data={"preview_url": new_url, "status": "active"},
        ))
    finally:
        _active_preview_repairs.discard(session_id)


async def _classify_change_request_bg(
    change_request_id: uuid.UUID,
    session_id: uuid.UUID,
) -> None:
    """Background task: classify a change request via Claude judge."""
    if not orchestrator.judge:
        return

    async with async_session_factory() as db:
        cr_result = await db.execute(
            select(ChangeRequest).where(ChangeRequest.id == change_request_id)
        )
        change_req = cr_result.scalar_one_or_none()
        if not change_req:
            return

        spec_result = await db.execute(
            select(RequirementSpec)
            .where(RequirementSpec.session_id == session_id)
            .where(RequirementSpec.confirmed == True)
            .order_by(RequirementSpec.version.desc())
        )
        spec = spec_result.scalar_one_or_none()
        requirements = spec.requirements_json if spec else {}

        sess_result = await db.execute(
            select(ProjectSession).where(ProjectSession.id == session_id)
        )
        session = sess_result.scalar_one_or_none()
        build_status = session.status if session else "unknown"

        classification = await orchestrator.judge.classify_change_request(
            user_comment=change_req.user_comment,
            requirements_json=requirements,
            current_build_status=build_status,
        )

        change_req.classification = classification.get("classification", "direct_tweak")
        change_req.structured_instruction = classification
        change_req.status = "needs_approval" if classification.get("requires_approval") else "pending"
        await db.commit()

        await event_bus.publish(ChangeRequestEvent(
            session_id=session_id,
            data={
                "change_request_id": str(change_request_id),
                "classification": change_req.classification,
                "instruction": classification.get("instruction", ""),
                "status": change_req.status,
            },
        ))


@router.get("", response_model=list[SessionResponse])
async def list_sessions(
    limit: int = 20,
    db: AsyncSession = Depends(get_session),
):
    """List internal sessions for the dashboard."""
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(ProjectSession)
        .options(selectinload(ProjectSession.showcase))
        .order_by(ProjectSession.created_at.desc())
        .limit(limit)
    )
    sessions = list(result.scalars().all())
    return [_session_response(session) for session in sessions]


# ── POST /sessions ─────────────────────────────────────────

@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(
    payload: SessionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """Create a new project session and immediately start the reverse interview."""
    session = ProjectSession(
        intake_mode=payload.intake_mode,
        build_mode=payload.build_mode,
        original_prompt=payload.prompt,
        github_repo_url=payload.github_url,
        status="created",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    await db.commit()  # commit before background task fires

    await event_bus.publish(SessionStatusEvent(
        session_id=session.id,
        data={"status": "created", "intake_mode": payload.intake_mode},
    ))

    # Bug 1 fix: immediately kick off the interview for prompt/github mode
    if payload.intake_mode in ("prompt", "github") and (payload.prompt or payload.github_url):
        background_tasks.add_task(orchestrator.start_interview, session.id)

    return _session_response(session)


# ── POST /sessions/{id}/intake ─────────────────────────────

@router.post("/{session_id}/intake", response_model=SessionResponse)
async def submit_intake(
    session_id: uuid.UUID,
    payload: IntakePayload,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """Submit code files or GitHub URL — persists, detects profile, starts interview."""
    session = await _get_session_or_404(session_id, db)

    if payload.github_url:
        session.github_repo_url = payload.github_url
        session.intake_mode = "github"

    # Bug 2 fix: persist pasted files and run profile detection
    if payload.files:
        session.intake_files_json = payload.files
        session.intake_mode = "paste"

        profile = detect_profile(payload.files)
        session.profile_type = profile.name

        # Build an interview prompt from the pasted code so Claude has context
        file_lines = []
        for name, content in payload.files.items():
            file_lines.append(f"File: {name}\n```\n{content[:3000]}\n```")
        session.original_prompt = (
            "[CODE INTAKE]\n"
            "The user has submitted existing code for analysis and hardening:\n\n"
            + "\n\n".join(file_lines)
        )

    session.status = "interviewing"
    await db.flush()
    await db.refresh(session)
    await db.commit()  # commit before background task fires

    await event_bus.publish(SessionStatusEvent(
        session_id=session.id,
        data={"status": "interviewing", "detail": "Code received, starting analysis"},
    ))

    # Start interview with the uploaded context
    background_tasks.add_task(orchestrator.start_interview, session.id)

    return _session_response(session)


# ── GET /sessions/{id}/interview ────────────────────────────

@router.get("/{session_id}/interview")
async def get_interview_history(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """Retrieve the conversation history for the interview phase."""
    result = await db.execute(
        select(RequirementSpec)
        .where(RequirementSpec.session_id == session_id)
        .order_by(RequirementSpec.version.desc())
    )
    spec = result.scalars().first()
    
    if not spec:
        return []
    
    return spec.interview_history or []


# ── POST /sessions/{id}/interview/answer ───────────────────

@router.post("/{session_id}/interview/answer")
async def answer_interview(
    session_id: uuid.UUID,
    payload: InterviewAnswer,
    db: AsyncSession = Depends(get_session),
):
    """User answers a reverse-interview question — forwards to Claude via orchestrator."""
    session = await _get_session_or_404(session_id, db)
    if session.status != "interviewing":
        raise HTTPException(
            status_code=400,
            detail=f"Session is not in interview phase (status={session.status})",
        )

    # Bug 3 fix: actually call the orchestrator instead of returning a stub
    result = await orchestrator.process_answer(session_id, payload.message)
    return result


# ── POST /sessions/{id}/requirements/confirm ──────────────

@router.post("/{session_id}/requirements/confirm", response_model=RequirementSpecResponse)
async def confirm_requirements(
    session_id: uuid.UUID,
    payload: RequirementConfirm,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """User confirms the RequirementSpec — triggers the parallel build phase."""
    session = await _get_session_or_404(session_id, db)

    result = await db.execute(
        select(RequirementSpec)
        .where(RequirementSpec.session_id == session_id)
        .where(RequirementSpec.confirmed == False)
        .order_by(RequirementSpec.version.desc())
    )
    spec = result.scalar_one_or_none()
    if spec is None:
        raise HTTPException(status_code=404, detail="No unconfirmed requirement spec found")

    spec.confirmed = payload.confirmed
    if payload.confirmed:
        session.status = "building"
    else:
        session.status = "spec_review"
    await db.flush()
    await db.refresh(spec)
    await db.commit()  # commit before background task fires

    await event_bus.publish(SessionStatusEvent(
        session_id=session.id,
        data={
            "status": session.status,
            "detail": "Requirements confirmed" if payload.confirmed else "Requirements rejected",
        },
    ))

    # Bug 4 fix (partial): confirming requirements immediately kicks off the build
    if payload.confirmed:
        _queue_session_task_once(background_tasks, session_id, orchestrator.start_build)

    return spec


# ── POST /sessions/{id}/build/start ────────────────────────

@router.post("/{session_id}/build/start")
async def start_build(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """Manually kick off the parallel build (if not auto-started by confirm)."""
    session = await _get_session_or_404(session_id, db)

    result = await db.execute(
        select(RequirementSpec)
        .where(RequirementSpec.session_id == session_id)
        .where(RequirementSpec.confirmed == True)
        .order_by(RequirementSpec.version.desc())
    )
    spec = result.scalar_one_or_none()
    if spec is None:
        raise HTTPException(status_code=400, detail="Requirements must be confirmed before building")

    if session.status in {"judging", "hardening", "complete"}:
        return {
            "status": session.status,
            "session_id": str(session_id),
            "detail": "Build phase already completed for this session",
        }

    if session_id in _active_tasks:
        return {
            "status": "building",
            "session_id": str(session_id),
            "detail": "Build already in progress",
        }

    session.status = "building"
    await db.flush()
    await db.commit()  # commit before background task fires

    await event_bus.publish(SessionStatusEvent(
        session_id=session.id,
        data={"status": "building", "detail": "Dual-provider build started"},
    ))

    # Bug 4 fix: call the orchestrator
    _queue_session_task_once(background_tasks, session_id, orchestrator.start_build)

    return {"status": "building", "session_id": str(session_id)}


# ── POST /sessions/{id}/comments ───────────────────────────

@router.post("/{session_id}/comments", response_model=ChangeRequestResponse)
async def submit_comment(
    session_id: uuid.UUID,
    payload: CommentSubmit,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """User submits a mid-build comment — persists and classifies via Claude."""
    session = await _get_session_or_404(session_id, db)

    change_request = ChangeRequest(
        session_id=session_id,
        user_comment=payload.comment,
        classification="pending",
        structured_instruction={},
        status="pending",
    )
    db.add(change_request)
    await db.flush()
    await db.refresh(change_request)
    await db.commit()  # commit before background task fires

    # Bug 6 fix: classify via Claude in the background
    background_tasks.add_task(
        _classify_change_request_bg, change_request.id, session_id
    )

    return change_request


# ── POST /sessions/{id}/hardening/start ────────────────────

@router.post("/{session_id}/hardening/start")
async def start_hardening(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """Manually start the Mark II hardening loop (auto-started after judging)."""
    session = await _get_session_or_404(session_id, db)

    result = await db.execute(
        select(BuildCandidate)
        .where(BuildCandidate.session_id == session_id)
        .where(BuildCandidate.is_baseline == True)
    )
    baseline = result.scalar_one_or_none()
    if baseline is None:
        raise HTTPException(status_code=400, detail="No baseline candidate selected")

    session.status = "hardening"
    await db.flush()
    await db.commit()  # commit before background task fires

    await event_bus.publish(SessionStatusEvent(
        session_id=session.id,
        data={"status": "hardening", "detail": "Mark II hardening initiated"},
    ))

    # Bug 4 fix: call the orchestrator
    background_tasks.add_task(orchestrator.start_hardening, session_id)

    return {"status": "hardening", "session_id": str(session_id)}


# ── GET /sessions/latest ───────────────────────────────────

@router.get("/latest", response_model=SessionResponse)
async def get_latest_session(
    db: AsyncSession = Depends(get_session),
):
    """Get the most recently created session."""
    result = await db.execute(
        select(ProjectSession)
        .order_by(ProjectSession.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="No sessions found")
    return _session_response(session)


# ── GET /sessions/{id} ────────────────────────────────────

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_detail(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """Get full session state. Auto-resumes building/hardening tasks if orphaned or stalled."""
    from datetime import datetime, timezone
    session = await _get_session_or_404(session_id, db)

    latest_mark_result = await db.execute(
        select(MarkRun)
        .where(MarkRun.session_id == session_id)
        .order_by(MarkRun.created_at.desc())
    )
    latest_mark = latest_mark_result.scalars().first()

    latest_activity = session.updated_at
    if latest_mark and latest_mark.created_at and (
        latest_activity is None or latest_mark.created_at > latest_activity
    ):
        latest_activity = latest_mark.created_at

    # Staleness threshold (10 minutes)
    is_stale = False
    if latest_activity:
        delta = datetime.now(timezone.utc) - latest_activity.replace(tzinfo=timezone.utc)
        if delta.total_seconds() > 600:  # 10 mins
            is_stale = True

    mark_count = await db.scalar(
        select(func.count())
        .select_from(MarkRun)
        .where(MarkRun.session_id == session_id)
    )
    hardening_exhausted = (mark_count or 0) >= settings.max_marks

    # Auto-resume: only kick off if NOT already active in this process AND truly stale
    # (stale = status stuck for >10 min without update, e.g. after server restart)
    is_active = session_id in _active_tasks
    should_resume = not is_active and is_stale

    if session.status == "building" and should_resume:
        _queue_session_task_once(background_tasks, session_id, orchestrator.start_build)
        logger.info("Auto-resuming stale building session %s", session_id)

    elif session.status == "hardening" and should_resume and not hardening_exhausted:
        _queue_session_task_once(background_tasks, session_id, orchestrator.start_hardening)
        logger.info("Auto-resuming stale hardening session %s", session_id)

    spec_result = await db.execute(
        select(RequirementSpec)
        .where(RequirementSpec.session_id == session_id)
        .order_by(RequirementSpec.version.desc())
    )
    spec = spec_result.scalar_one_or_none()

    baseline_result = await db.execute(
        select(BuildCandidate)
        .where(BuildCandidate.session_id == session_id)
        .where(BuildCandidate.is_baseline == True)
        .order_by(BuildCandidate.created_at.desc())
    )
    baseline = baseline_result.scalar_one_or_none()
    preview_mode = _resolve_preview_mode(
        session,
        spec,
        baseline.files_json if baseline else None,
    )

    return _session_response(session, preview_mode=preview_mode)


# ── GET /sessions/{id}/events ──────────────────────────────

@router.get("/{session_id}/events")
async def session_events(session_id: uuid.UUID):
    """SSE stream of real-time session events."""
    return StreamingResponse(
        event_bus.stream(session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── GET /sessions/{id}/preview ─────────────────────────────

@router.get("/{session_id}/preview")
async def get_preview(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """Get the current preview URL/status. Auto-restores if dead."""
    return await _resolve_preview_state(session_id, background_tasks, db)


@router.get("/{session_id}/preview/openapi")
async def get_preview_openapi(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """Proxy the preview's OpenAPI document through the backend to avoid browser CORS issues."""
    preview_state = await _resolve_preview_state(session_id, background_tasks, db)
    if preview_state["status"] != "active" or not preview_state["preview_url"]:
        raise HTTPException(status_code=409, detail=preview_state.get("detail") or "Preview is not active")

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{preview_state['preview_url']}/openapi.json", timeout=10.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=exc.response.status_code, detail="OpenAPI schema unavailable") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to load OpenAPI schema: {exc}") from exc


@router.post("/{session_id}/preview/request")
async def proxy_preview_request(
    session_id: uuid.UUID,
    payload: PreviewRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_session),
):
    """Proxy API Playground requests through the backend so sandbox CORS does not matter."""
    preview_state = await _resolve_preview_state(session_id, background_tasks, db)
    if preview_state["status"] != "active" or not preview_state["preview_url"]:
        raise HTTPException(status_code=409, detail=preview_state.get("detail") or "Preview is not active")

    method = payload.method.upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}:
        raise HTTPException(status_code=400, detail="Unsupported preview request method")

    path = _normalize_preview_path(payload.path)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method,
                f"{preview_state['preview_url']}{path}",
                timeout=15.0,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to reach preview service: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    body: object | None
    if not response.content:
        body = None
    elif "application/json" in content_type:
        try:
            body = response.json()
        except Exception:
            body = response.text
    else:
        body = response.text

    return {
        "status_code": response.status_code,
        "ok": response.is_success,
        "method": method,
        "path": path,
        "body": body,
    }


# ── GET /sessions/{id}/candidates ─────────────────────────

@router.get("/{session_id}/candidates")
async def get_candidates(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """Get all build candidates for a session."""
    await _get_session_or_404(session_id, db)
    result = await db.execute(
        select(BuildCandidate)
        .where(BuildCandidate.session_id == session_id)
        .order_by(BuildCandidate.created_at.asc())
    )
    candidates = list(result.scalars().all())
    return [
        {
            "candidate_id": str(c.id),
            "provider": c.provider,
            "model": c.model,
            "status": c.status,
            "is_baseline": c.is_baseline,
            "score": c.score,
            "build_duration_ms": c.build_duration_ms,
            "build_log": c.build_log,
            "module_scope_json": c.module_scope_json or {},
            "review_notes_json": c.review_notes_json or [],
            "candidate_format": c.candidate_format,
            "patch_summary": c.patch_summary,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in candidates
    ]


# ── GET /sessions/{id}/marks ────────────────────────────────

@router.get("/{session_id}/marks")
async def get_session_marks(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """Get the history of hardening iteration results (Mark Runs)."""
    await _get_session_or_404(session_id, db)
    result = await db.execute(
        select(MarkRun)
        .where(MarkRun.session_id == session_id)
        .order_by(MarkRun.mark_number.asc())
    )
    runs = list(result.scalars().all())
    return [
        {
            "id": str(r.id),
            "mark_number": r.mark_number,
            "mark_name": r.mark_name,
            "passed": r.passed,
            "result_type": _derive_mark_result_type(r),
            "failure_type": r.failure_type,
            "rejection_reason": r.rejection_reason,
            "patch_summary": r.patch_summary,
            "score": r.score,
        }
        for r in runs
    ]


# ── GET /sessions/{id}/judge ────────────────────────────────

@router.get("/{session_id}/judge")
async def get_judge_decision(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """Get the judge decision for a session."""
    from app.models.judge import JudgeDecision
    await _get_session_or_404(session_id, db)
    result = await db.execute(
        select(JudgeDecision)
        .where(JudgeDecision.session_id == session_id)
        .order_by(JudgeDecision.created_at.desc())
    )
    decision = result.scalar_one_or_none()
    if not decision:
        return {"winner": None, "reasoning": None, "scores": {}}

    # Resolve winner provider name from the winning candidate
    winner_provider = None
    if decision.winning_candidate_id:
        cr = await db.execute(
            select(BuildCandidate).where(BuildCandidate.id == decision.winning_candidate_id)
        )
        winner_candidate = cr.scalar_one_or_none()
        if winner_candidate:
            winner_provider = winner_candidate.provider

    return {
        "winner": winner_provider,
        "reasoning": decision.reasoning,
        "scores": decision.scores_json or {},
    }


# ── GET /sessions/{id}/artifacts ───────────────────────────

@router.get("/{session_id}/artifacts")
async def get_artifacts(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """Get the final delivery artifacts — returns baseline candidate files."""
    await _get_session_or_404(session_id, db)

    # Prefer the most recently repaired (highest-mark) candidate with files
    result = await db.execute(
        select(BuildCandidate)
        .where(BuildCandidate.session_id == session_id)
        .where(BuildCandidate.is_baseline == True)
    )
    baseline = result.scalar_one_or_none()

    # Fallback: any built candidate if baseline not set yet
    if not baseline:
        result = await db.execute(
            select(BuildCandidate)
            .where(BuildCandidate.session_id == session_id)
            .where(BuildCandidate.status == "built")
            .order_by(BuildCandidate.created_at.desc())
        )
        baseline = result.scalar_one_or_none()

    files = {}
    if baseline and baseline.files_json:
        files = dict(baseline.files_json)

    from app.models.session import ProjectSession
    sess_result = await db.execute(select(ProjectSession).where(ProjectSession.id == session_id))
    session = sess_result.scalar_one_or_none()

    return {
        "session_id": str(session_id),
        "status": session.status if session else "unknown",
        "provider": baseline.provider if baseline else None,
        "model": baseline.model if baseline else None,
        "artifacts": files,
        "build_log": baseline.build_log if baseline else None,
    }


# ── Project Chronicle (Showcase) ───────────────────────────

@router.post("/{session_id}/showcase/generate", response_model=ShowcaseResponse)
async def generate_showcase(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """Trigger the autonomous generation of a project showcase."""
    # Check if baseline exists
    result = await db.execute(
        select(BuildCandidate)
        .where(BuildCandidate.session_id == session_id)
        .where(BuildCandidate.is_baseline == True)
    )
    baseline = result.scalar_one_or_none()
    if not baseline:
        raise HTTPException(status_code=400, detail="Cannot generate showcase: No baseline candidate selected.")

    showcase = await showcase_service.generate_showcase(session_id)
    if not showcase:
        raise HTTPException(status_code=500, detail="Showcase generation failed")
    
    return showcase


@router.get("/{session_id}/showcase", response_model=ShowcaseResponse)
async def get_showcase(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
):
    """Retrieve the showcase for a session. Auto-generates if missing."""
    from app.models.showcase import SessionShowcase
    result = await db.execute(
        select(SessionShowcase).where(SessionShowcase.session_id == session_id)
    )
    showcase = result.scalar_one_or_none()
    
    if not showcase:
        # Check if we can auto-generate
        result = await db.execute(
            select(BuildCandidate)
            .where(BuildCandidate.session_id == session_id)
            .where(BuildCandidate.is_baseline == True)
        )
        baseline = result.scalar_one_or_none()
        if baseline:
            logger.info("Self-healing: Auto-generating missing showcase for session %s", session_id)
            showcase = await showcase_service.generate_showcase(session_id)
    
    if not showcase:
        raise HTTPException(status_code=404, detail="Showcase not found and could not be auto-generated")
    
    # Increment view count
    showcase.view_count += 1
    await db.commit()
    
    return showcase
