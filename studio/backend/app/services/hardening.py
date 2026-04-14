"""
Mark II Studio — Hardening Service
Manages the autonomous Mark I-VII build-break-heal cycle.
"""
from __future__ import annotations

import uuid
import asyncio
import logging
import re
from datetime import datetime, timezone
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

_REPAIR_STOPWORDS = {
    "the", "and", "with", "from", "that", "this", "into", "while", "under",
    "during", "caused", "server", "failed", "failure", "critical", "attack",
    "detected", "error", "status", "details", "unknown", "mark", "phase",
}


class HardeningService:
    """
    Coordinates the autonomous hardening loop.
    Iteratively attacks and repairs code to reach Mark VII.
    """

    def __init__(self) -> None:
        self.builder = OpenAIBuilder()
        self.agent = AdversaryAgent(
            model=settings.openai_adversary_model or settings.openai_builder_model
        )
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
                        # Unrecoverable — mark complete so UI stops polling
                        async with async_session_factory() as db:
                            session_obj = await self._get_session(db, session_id)
                            session_obj.status = "complete"
                            await db.commit()
                        await event_bus.publish(SessionStatusEvent(
                            session_id=session_id,
                            data={"status": "complete", "detail": "Service failed to start — hardening stopped"},
                        ))
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
                    result_type, primary_phase = _derive_report_result_type(phases)
                    passed = result_type == "passed"
                    critical_failures = sum(1 for p in phases if _phase_result_type(p) == "breach")
                    inconclusive_failures = sum(1 for p in phases if _phase_result_type(p) == "inconclusive")
                    report = SwarmReport(
                        base_url=base_url,
                        passed=passed,
                        phases=phases,
                        summary={
                            "critical_failures": critical_failures,
                            "inconclusive_failures": inconclusive_failures,
                            "passed_phases": sum(1 for p in phases if _phase_result_type(p) == "passed"),
                            "verdict": (
                                "Armor Holds"
                                if result_type == "passed"
                                else "Breach Detected"
                                if result_type == "breach"
                                else "Attack Inconclusive"
                            ),
                            "result_type": result_type,
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
                        repair_failed = False

                        if not report.passed:
                            issue_phase = primary_phase or report.phases[0]
                            mark_run.failure_type = _classify_mark_failure(
                                issue_phase.name,
                                issue_phase.details,
                            )
                            mark_run.rejection_reason = "\n".join(issue_phase.details)

                            if result_type == "breach":
                                logger.warning("Mark %s FAILED: %s", mark_name, mark_run.failure_type)

                                await event_bus.publish(SessionStatusEvent(
                                    session_id=session_id,
                                    data={"status": "hardening", "detail": "Vulnerability detected — repair engineer patching…"},
                                ))

                                target_file, context_files = _select_repair_context(
                                    current_files,
                                    profile_type=profile_type,
                                    failure_type=mark_run.failure_type or "",
                                    failure_details=mark_run.rejection_reason or "",
                                )
                                repair_requirements = _compact_repair_requirements(requirements_json)
                                logger.info(
                                    "Repair focus for Mark %s: target=%s context_files=%s",
                                    mark_name,
                                    target_file,
                                    list(context_files.keys()),
                                )

                                repair_result = await self.builder.repair(
                                    failure_type=mark_run.failure_type,
                                    source_files=current_files,
                                    failure_details=mark_run.rejection_reason,
                                    requirements_json=repair_requirements,
                                    target_file=target_file,
                                    context_files=context_files,
                                )

                                repaired_files = repair_result.get("files") or {}
                                repair_error = (repair_result.get("error") or "").strip()
                                repair_changed = bool(repaired_files) and repaired_files != current_files
                                if repair_changed:
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
                                    repair_failed = True
                                    patch_summary = repair_result.get("summary") or "Repair failed"
                                    if repair_error and repair_error not in patch_summary:
                                        patch_summary = f"{patch_summary}: {repair_error}"
                                    mark_run.patch_summary = patch_summary
                                    logger.error("Mark %s: repair failed (%s)", mark_name, patch_summary)
                            else:
                                mark_run.patch_summary = "No repair applied because the attack outcome was inconclusive."
                                logger.warning("Mark %s inconclusive: %s", mark_name, mark_run.failure_type)
                                await event_bus.publish(SessionStatusEvent(
                                    session_id=session_id,
                                    data={"status": "hardening", "detail": "Attack outcome inconclusive — continuing without repair…"},
                                ))
                        else:
                            logger.info("Mark %s: ARMOR HOLDS", mark_name)

                        db.add(mark_run)

                        await event_bus.publish(MarkResultEvent(
                            session_id=session_id,
                            data={
                                "mark_number": mark_number,
                                "mark_name": mark_name,
                                "passed": report.passed,
                                "result_type": result_type,
                                "failure_type": mark_run.failure_type,
                                "rejection_reason": mark_run.rejection_reason,
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

                        if repair_failed:
                            session_obj = await self._get_session(db, session_id)
                            session_obj.status = "complete"
                            await db.commit()

                            await event_bus.publish(ErrorEvent(
                                session_id=session_id,
                                data={
                                    "error": mark_run.patch_summary,
                                    "detail": f"Repair engineer could not patch Mark {mark_name}",
                                },
                            ))
                            await event_bus.publish(SessionStatusEvent(
                                session_id=session_id,
                                data={"status": "complete", "detail": "Repair failed — manual review recommended"},
                            ))
                            return

                        session_obj = await self._get_session(db, session_id)
                        session_obj.updated_at = datetime.now(timezone.utc)
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
                # Persist status first so polling clients see "complete" even if SSE is lost
                try:
                    async with async_session_factory() as db:
                        session_obj = await self._get_session(db, session_id)
                        session_obj.status = "complete"
                        await db.commit()
                except Exception:
                    pass
                # Publish after DB write so SSE subscribers (if still connected) also get it
                await event_bus.publish(ErrorEvent(
                    session_id=session_id,
                    data={"error": str(e), "detail": "Hardening loop crashed"},
                ))
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": "complete", "detail": "Hardening failed — session marked complete"},
                ))

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


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}... [truncated]"


def _compact_repair_requirements(requirements_json: dict) -> dict:
    def _compact_list(items: list, max_items: int, max_chars: int) -> list:
        compacted: list = []
        for item in items[:max_items]:
            if isinstance(item, dict):
                compacted.append({
                    key: _truncate_text(str(value), max_chars)
                    for key, value in list(item.items())[:6]
                })
            else:
                compacted.append(_truncate_text(str(item), max_chars))
        omitted = len(items) - len(compacted)
        if omitted > 0:
            compacted.append(f"... {omitted} additional items omitted")
        return compacted

    return {
        "functional": _compact_list(requirements_json.get("functional", []), max_items=8, max_chars=180),
        "routes_or_pages": _compact_list(requirements_json.get("routes_or_pages", []), max_items=8, max_chars=140),
        "data_model": _compact_list(requirements_json.get("data_model", []), max_items=6, max_chars=160),
        "security": _compact_list(requirements_json.get("security", []), max_items=6, max_chars=160),
        "behavior": _compact_list(requirements_json.get("behavior", []), max_items=6, max_chars=160),
        "technical": _compact_list(requirements_json.get("technical", []), max_items=6, max_chars=160),
    }


def _extract_failure_keywords(failure_type: str, failure_details: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-zA-Z_]{3,}", f"{failure_type} {failure_details}".lower())
        if token not in _REPAIR_STOPWORDS
    }
    expanded = set(tokens)
    if any(token in tokens for token in {"json", "payload", "boundary", "path", "probe", "endpoint"}):
        expanded.update({"api", "route", "validation", "request"})
    if any(token in tokens for token in {"race", "flood", "concurrent"}):
        expanded.update({"lock", "balance", "transfer", "reset"})
    return expanded


def _classify_mark_failure(phase_name: str, details: list[str]) -> str:
    joined = " ".join(details).lower()
    if any(
        marker in joined
        for marker in (
            "judge unavailable",
            "judge error",
            "request failed",
            "request/judge failed",
            "probe synthesis failed",
        )
    ):
        return "AttackExecutionFailure"
    return phase_name


def _phase_result_type(phase: PhaseResult) -> str:
    outcome = str((phase.metrics or {}).get("outcome") or "").lower()
    if outcome == "breach":
        return "breach"
    if outcome in {"execution_failed", "judge_unavailable", "probe_synthesis_failed", "inconclusive"}:
        return "inconclusive"
    if phase.critical and not phase.passed:
        return "breach"
    if not phase.passed:
        return "inconclusive"
    return "passed"


def _derive_report_result_type(phases: list[PhaseResult]) -> tuple[str, PhaseResult | None]:
    for phase in phases:
        if _phase_result_type(phase) == "breach":
            return "breach", phase
    for phase in phases:
        if _phase_result_type(phase) == "inconclusive":
            return "inconclusive", phase
    return "passed", None


def _source_file_priority(path: str, profile_type: str) -> int:
    path_lower = path.lower()
    if profile_type == "fastapi_service":
        if path_lower == "main.py":
            return 120
        if path_lower in {"app.py", "server.py"}:
            return 110
        if path_lower.endswith(".py"):
            return 70
    if profile_type == "nextjs_webapp":
        if "/api/" in path_lower and path_lower.endswith(("route.ts", "route.js")):
            return 120
        if path_lower in {"app/page.tsx", "src/app/page.tsx"}:
            return 110
        if path_lower in {"app/layout.tsx", "src/app/layout.tsx"}:
            return 100
        if path_lower.endswith((".tsx", ".ts", ".jsx", ".js")):
            return 70
    if path_lower.endswith((".py", ".ts", ".tsx", ".js", ".jsx")):
        return 50
    return 0


def _score_repair_file(
    path: str,
    content: str,
    profile_type: str,
    failure_keywords: set[str],
) -> int:
    path_lower = path.lower()
    content_lower = content.lower()
    score = _source_file_priority(path, profile_type)

    if any(marker in path_lower for marker in ("test", ".spec.", ".test.")):
        score -= 40
    if path_lower.endswith(("requirements.txt", "package.json", "tsconfig.json", "next.config.js", "next.config.mjs")):
        score -= 20

    for keyword in failure_keywords:
        if keyword in path_lower:
            score += 25
        if keyword in content_lower:
            score += 4

    if any(token in failure_keywords for token in {"api", "route", "request", "validation"}):
        if "/api/" in path_lower or path_lower.endswith(".py") or "route." in path_lower:
            score += 20
    if any(token in failure_keywords for token in {"lock", "race", "concurrent"}):
        if any(token in content_lower for token in ("lock", "asyncio", "mutex")):
            score += 20

    return score


def _select_repair_context(
    current_files: dict[str, str],
    *,
    profile_type: str,
    failure_type: str,
    failure_details: str,
) -> tuple[str, dict[str, str]]:
    if not current_files:
        return "main.py", {}

    failure_keywords = _extract_failure_keywords(failure_type, failure_details)
    ranked = sorted(
        current_files.items(),
        key=lambda item: (
            _score_repair_file(item[0], item[1], profile_type, failure_keywords),
            item[0],
        ),
        reverse=True,
    )

    target_file = ranked[0][0]
    context_files: dict[str, str] = {target_file: current_files[target_file]}

    for path, content in ranked[1:]:
        if len(context_files) >= 4:
            break
        if _source_file_priority(path, profile_type) <= 0:
            continue
        context_files[path] = content

    for config_name in ("requirements.txt", "package.json", "tsconfig.json"):
        if len(context_files) >= 6:
            break
        if config_name in current_files and config_name not in context_files:
            context_files[config_name] = current_files[config_name]

    return target_file, context_files


# Singleton
hardening_service = HardeningService()
