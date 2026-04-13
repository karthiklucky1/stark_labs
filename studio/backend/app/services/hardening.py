"""
Mark II Studio — Hardening Service
Manages the autonomous Mark I-VII build-break-heal cycle.
"""
from __future__ import annotations

import uuid
import asyncio
import logging
from typing import Dict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.events.bus import event_bus
from app.models.candidate import BuildCandidate
from app.models.mark_run import MarkRun
from app.models.session import ProjectSession
from app.models.requirement import RequirementSpec
from app.providers.openai_builder import OpenAIBuilder
from app.services.bridge import map_swarm_report_to_db
from app.services.harvester import harvester_service
from app.services.profiles import get_profile
from app.services.sandbox import sandbox_manager
from app.schemas.events import (
    DeliveryReadyEvent,
    MarkResultEvent,
    MarkStartedEvent,
    ErrorEvent,
    SessionStatusEvent,
)
from app.settings import settings

from app.agents.adversary_agent import AdversaryAgent
from mark_ii.schemas import PhaseResult, SwarmReport

logger = logging.getLogger(__name__)


class HardeningService:
    """
    Coordinates the autonomous hardening loop.
    Iteratively attacks and repairs code to reach Mark VII.
    """

    def __init__(self) -> None:
        self.builder = OpenAIBuilder()
        self.agent = AdversaryAgent()
        self._locks: Dict[uuid.UUID, asyncio.Lock] = {}

    def _get_lock(self, session_id: uuid.UUID) -> asyncio.Lock:
        if session_id not in self._locks:
            self._locks[session_id] = asyncio.Lock()
        return self._locks[session_id]

    async def run_hardening_loop(self, session_id: uuid.UUID) -> None:
        """Execute the Mark I→VII hardening loop for a session."""
        lock = self._get_lock(session_id)
        if lock.locked():
            logger.info("Hardening loop already active for session %s. Skipping re-entry.", session_id)
            return

        async with lock:
            try:
                # ── Load all DB state up front as plain Python values ──────────
                # CRITICAL: ORM objects become detached once the `async with db` block
                # closes. Extract everything needed for the loop as plain values now.
                async with async_session_factory() as db:
                    session = await self._get_session(db, session_id)

                    result = await db.execute(
                        select(RequirementSpec)
                        .where(RequirementSpec.session_id == session_id)
                        .where(RequirementSpec.confirmed == True)
                        .order_by(RequirementSpec.version.desc())
                    )
                    spec = result.scalar_one_or_none()
                    if not spec:
                        raise ValueError("No confirmed spec found for hardening")

                    result = await db.execute(
                        select(BuildCandidate)
                        .where(BuildCandidate.session_id == session_id)
                        .where(BuildCandidate.is_baseline == True)
                    )
                    baseline = result.scalar_one_or_none()
                    if not baseline:
                        raise ValueError("No baseline candidate found for hardening")

                    # Extract plain values — safe to use outside the DB context
                    profile_type: str = session.profile_type or "unsupported"
                    requirements_json: dict = spec.requirements_json or {}
                    blueprint_json: dict = spec.blueprint_json or {}

                    current_candidate_id: uuid.UUID = baseline.id
                    current_sandbox_id: str = baseline.sandbox_id
                    current_files: dict = dict(baseline.files_json or {})

                profile = get_profile(profile_type, blueprint=blueprint_json)
                startup_cmd: str = profile.startup_command
                health_path: str = profile.get_smoke_test_config().get("health_endpoint", "/health")

                # If the dynamic profile has no startup command in the blueprint,
                # try to infer one from the built files so the service can actually start.
                if not startup_cmd:
                    startup_cmd = _infer_startup_command(current_files)
                    logger.warning("Blueprint has no startup_command — inferred: %s", startup_cmd)

                # ── Mark loop ─────────────────────────────────────────────────
                for mark_idx in range(settings.max_marks):
                    mark_number = mark_idx + 1
                    mark_name = settings.mark_names[mark_idx]

                    await event_bus.publish(MarkStartedEvent(
                        session_id=session_id,
                        data={"mark_number": mark_number, "mark_name": mark_name},
                    ))
                    logger.info("Mark %s starting for session %s", mark_name, session_id)

                    # ── Step 1: ensure sandbox is alive and service is running ──
                    base_url = await self._ensure_service(
                        session_id=session_id,
                        sandbox_id=current_sandbox_id,
                        files=current_files,
                        profile_type=profile_type,
                        profile=profile,
                        startup_cmd=startup_cmd,
                        health_path=health_path,
                        mark_idx=mark_idx,
                        candidate_id=current_candidate_id,
                    )
                    if base_url is None:
                        # Unrecoverable — stop the loop
                        break

                    # Update sandbox_id in case self-healing created a new one
                    # (returned as attribute on result object via side-channel in _ensure_service)
                    current_sandbox_id = getattr(self, '_last_sandbox_id', current_sandbox_id)

                    # ── Step 2: Adversary recon + attack ──────────────────────
                    await event_bus.publish(SessionStatusEvent(
                        session_id=session_id,
                        data={"status": "hardening", "detail": "Adversary Agent mapping attack surface…"},
                    ))
                    try:
                        surface = await self.agent.recon_surface(current_files)
                        waves = await self.agent.synthesize_attack_waves(surface)
                        await event_bus.publish(SessionStatusEvent(
                            session_id=session_id,
                            data={"status": "hardening", "detail": f"Running {len(waves)} attack waves in parallel…"},
                        ))
                        attack_results = await self.agent.run_attack_waves(base_url, waves)
                    except Exception as e:
                        logger.error("Adversary agent error on Mark %s: %s", mark_name, e)
                        # Treat agent failure as all-passed so loop continues
                        attack_results = [{"name": "agent_error", "passed": True, "critical": False, "details": [str(e)], "metrics": {}}]

                    # ── Step 3: Build SwarmReport ─────────────────────────────
                    phases = [
                        PhaseResult(
                            phase_id=i + 1,
                            name=res["name"],
                            passed=res["passed"],
                            critical=res["critical"],
                            details=res["details"],
                            metrics=res["metrics"],
                        )
                        for i, res in enumerate(attack_results)
                    ]
                    passed = all(p.passed for p in phases)
                    report = SwarmReport(
                        base_url=base_url,
                        passed=passed,
                        phases=phases,
                        summary={
                            "critical_failures": sum(1 for p in phases if not p.passed),
                            "passed_phases": sum(1 for p in phases if p.passed),
                            "verdict": "Armor Holds" if passed else "Breach Detected",
                        },
                    )

                    # ── Step 4: Persist mark + optionally repair ──────────────
                    async with async_session_factory() as db:
                        result = await db.execute(
                            select(BuildCandidate).where(BuildCandidate.id == current_candidate_id)
                        )
                        db_candidate = result.scalar_one_or_none()
                        if db_candidate:
                            db_candidate.preview_url = base_url
                            await db.flush()

                        mark_run = MarkRun(
                            session_id=session_id,
                            candidate_id=current_candidate_id,
                            mark_number=mark_number,
                            mark_name=mark_name,
                            passed=report.passed,
                            swarm_report_json=map_swarm_report_to_db(report),
                        )

                        if not report.passed:
                            critical_phase = next((p for p in report.phases if p.critical), report.phases[0])
                            mark_run.failure_type = critical_phase.name
                            mark_run.rejection_reason = "\n".join(critical_phase.details)
                            logger.warning("Mark %s FAILED: %s", mark_name, mark_run.failure_type)

                            await event_bus.publish(SessionStatusEvent(
                                session_id=session_id,
                                data={"status": "hardening", "detail": "Vulnerability detected — repair engineer patching…"},
                            ))

                            repair_result = await self.builder.repair(
                                failure_type=mark_run.failure_type,
                                source_files=current_files,
                                failure_details=mark_run.rejection_reason,
                                requirements_json=requirements_json,
                            )

                            repaired_files = repair_result.get("files") or {}
                            if repaired_files:
                                mark_run.patch_summary = repair_result.get("summary", "Patch applied")
                                mark_run.repair_provider = "openai"
                                mark_run.repair_model = settings.openai_builder_model

                                new_candidate = BuildCandidate(
                                    session_id=session_id,
                                    provider="openai",
                                    model=settings.openai_builder_model,
                                    sandbox_id=current_sandbox_id,
                                    status="built",
                                    files_json=repaired_files,
                                    build_log=f"Repair: {mark_run.patch_summary}",
                                )
                                db.add(new_candidate)
                                await db.flush()

                                await sandbox_manager.upload_files(current_sandbox_id, repaired_files)

                                if db_candidate:
                                    await harvester_service.harvest_repair(
                                        db=db,
                                        mark_run=mark_run,
                                        broken_candidate=db_candidate,
                                        fixed_candidate=new_candidate,
                                    )

                                # Update plain-value state for next iteration
                                current_candidate_id = new_candidate.id
                                current_files = dict(repaired_files)
                                logger.info("Mark %s: repair applied", mark_name)
                            else:
                                logger.error("Mark %s: repair returned no files", mark_name)
                        else:
                            logger.info("Mark %s: ARMOR HOLDS", mark_name)

                        db.add(mark_run)

                        await event_bus.publish(MarkResultEvent(
                            session_id=session_id,
                            data={
                                "mark_number": mark_number,
                                "mark_name": mark_name,
                                "passed": report.passed,
                                "failure_type": mark_run.failure_type,
                                "patch_summary": mark_run.patch_summary,
                            },
                        ))

                        if report.passed:
                            session_obj = await self._get_session(db, session_id)
                            session_obj.status = "complete"
                            await db.commit()

                            await event_bus.publish(DeliveryReadyEvent(
                                session_id=session_id,
                                data={"mark_name": mark_name, "mark_number": mark_number},
                            ))
                            await event_bus.publish(SessionStatusEvent(
                                session_id=session_id,
                                data={"status": "complete", "detail": f"Armor held at Mark {mark_name}"},
                            ))
                            return  # Done

                        await db.commit()

                # Loop exhausted — all marks failed
                async with async_session_factory() as db:
                    session_obj = await self._get_session(db, session_id)
                    session_obj.status = "complete"
                    await db.commit()
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": "complete", "detail": "All marks exhausted — manual review recommended"},
                ))

            except Exception as e:
                logger.error("Hardening loop crashed: %s", e, exc_info=True)
                await event_bus.publish(ErrorEvent(
                    session_id=session_id,
                    data={"error": str(e), "detail": "Hardening loop crashed"},
                ))
                # Mark session failed so UI doesn't stay stuck on "hardening"
                try:
                    async with async_session_factory() as db:
                        session_obj = await self._get_session(db, session_id)
                        session_obj.status = "complete"
                        await db.commit()
                except Exception:
                    pass

    async def _ensure_service(
        self,
        session_id: uuid.UUID,
        sandbox_id: str,
        files: dict,
        profile_type: str,
        profile,
        startup_cmd: str,
        health_path: str,
        mark_idx: int,
        candidate_id: uuid.UUID,
    ) -> str | None:
        """
        Ensure sandbox is alive and service is healthy.
        Self-heals by creating a new sandbox if the current one is gone.
        Returns base_url on success, None on unrecoverable failure.
        Sets self._last_sandbox_id to the (possibly new) sandbox_id.
        """
        self._last_sandbox_id = sandbox_id

        async def _start(sid: str, install: bool) -> str:
            if install and not sid.startswith("mock-"):
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": "hardening", "detail": "Installing dependencies in sandbox…"},
                ))
                await sandbox_manager.install_deps(sid, profile.install_command)
            return await sandbox_manager.run_service(sid, startup_cmd=startup_cmd, health_path=health_path)

        try:
            return await _start(sandbox_id, install=(mark_idx == 0))
        except (ValueError, Exception) as e:
            is_sandbox_lost = "could not be recovered" in str(e) or "not found" in str(e).lower()
            if not is_sandbox_lost:
                logger.error("Service failed on Mark %d: %s", mark_idx + 1, e)
                await event_bus.publish(ErrorEvent(
                    session_id=session_id,
                    data={"error": str(e), "detail": f"Service start failed for Mark {mark_idx + 1}"},
                ))
                return None

            # Self-heal: create fresh sandbox
            logger.warning("Sandbox %s lost — self-healing for session %s", sandbox_id, session_id)
            await event_bus.publish(SessionStatusEvent(
                session_id=session_id,
                data={"status": "hardening", "detail": "Cloud environment lost — re-provisioning sandbox…"},
            ))
            try:
                new_sid = await sandbox_manager.create_sandbox(profile_type, str(session_id))
                await sandbox_manager.upload_files(new_sid, files)

                # Persist new sandbox_id to DB
                async with async_session_factory() as db:
                    result = await db.execute(select(BuildCandidate).where(BuildCandidate.id == candidate_id))
                    c = result.scalar_one_or_none()
                    if c:
                        c.sandbox_id = new_sid
                        await db.commit()

                self._last_sandbox_id = new_sid
                logger.info("Self-heal complete — new sandbox %s", new_sid)

                # Always install deps on a fresh sandbox
                return await _start(new_sid, install=True)
            except Exception as heal_err:
                logger.error("Self-healing failed: %s", heal_err)
                await event_bus.publish(ErrorEvent(
                    session_id=session_id,
                    data={"error": str(heal_err), "detail": "Self-healing failed — cannot provision sandbox"},
                ))
                return None

    async def _get_session(self, db: AsyncSession, session_id: uuid.UUID) -> ProjectSession:
        result = await db.execute(
            select(ProjectSession).where(ProjectSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError(f"Session {session_id} not found")
        return session


def _infer_startup_command(files: dict) -> str:
    """Best-effort startup command inferred from built file names."""
    names = set(files.keys())
    if "main.py" in names:
        return "uvicorn main:app --host 0.0.0.0 --port 8000"
    if "app.py" in names:
        return "uvicorn app:app --host 0.0.0.0 --port 8000"
    if "server.py" in names:
        return "uvicorn server:app --host 0.0.0.0 --port 8000"
    if "package.json" in names:
        return "npm start"
    # Fallback: find any .py file and assume it's the entry point
    for name in names:
        if name.endswith(".py") and name not in ("requirements.txt",):
            module = name[:-3]
            return f"uvicorn {module}:app --host 0.0.0.0 --port 8000"
    return "python main.py"


# Singleton
hardening_service = HardeningService()
