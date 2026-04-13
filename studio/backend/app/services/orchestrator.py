"""
Mark II Studio — Master Orchestrator
The session state machine that coordinates the entire build pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.events.bus import event_bus
from app.models.session import ProjectSession
from app.models.requirement import RequirementSpec
from app.models.candidate import BuildCandidate
from app.models.judge import JudgeDecision
from app.providers.openai_builder import OpenAIBuilder
from app.providers.deepseek_builder import DeepSeekBuilder
from app.providers.zhipu_builder import ZhipuBuilder
from app.providers.claude_interviewer import ClaudeInterviewer
from app.providers.claude_judge import ClaudeJudge
from app.providers.ollama_builder import OllamaBuilder
from app.services.profiles import detect_profile, get_profile
from app.services.sandbox import sandbox_manager
from app.services.hardening import hardening_service
from app.schemas.events import (
    BuildProgressEvent,
    CandidateReadyEvent,
    InterviewMessageEvent,
    JudgeResultEvent,
    SessionStatusEvent,
    ErrorEvent,
)
from app.settings import settings

logger = logging.getLogger(__name__)


def _resolve_runtime_profile(
    session: ProjectSession,
    spec: RequirementSpec | None,
    files: dict[str, str] | None,
):
    files = files or {}
    profile = get_profile(
        session.profile_type or "unsupported",
        blueprint=spec.blueprint_json if spec else None,
    )
    runtime_profile = profile

    if files and (profile.name in {"dynamic_profile", "unsupported"} or not profile.startup_command or not profile.install_command):
        detected = detect_profile(files)
        if detected.name != "unsupported":
            runtime_profile = detected

    startup_cmd = runtime_profile.startup_command or profile.startup_command
    install_cmd = runtime_profile.install_command or profile.install_command
    health_path = (
        runtime_profile.get_smoke_test_config().get("health_endpoint")
        or profile.get_smoke_test_config().get("health_endpoint")
        or "/health"
    )
    return profile, runtime_profile, startup_cmd, install_cmd, health_path


class Orchestrator:
    """
    Master orchestrator implementing the session state machine.

    Flow: Created → Interviewing → SpecReview → Building → Judging → Hardening → Complete
    """

    def __init__(self) -> None:
        self.openai_builder = OpenAIBuilder()

        # Optional providers — only init if keys are configured
        self.deepseek_builder = DeepSeekBuilder() if settings.has_deepseek else None
        self.zhipu_builder = ZhipuBuilder() if settings.has_zhipu else None
        self.ollama_builder = OllamaBuilder() if settings.has_ollama else None
        self.interviewer = ClaudeInterviewer() if settings.has_anthropic else None
        self.judge = ClaudeJudge() if settings.has_anthropic else None
        self._session_locks: dict[uuid.UUID, asyncio.Lock] = {}

        logger.info(
            "Orchestrator ready — OpenAI=%s, DeepSeek=%s, Zhipu=%s, Claude=%s, E2B=%s",
            "✅", "✅" if self.deepseek_builder else "❌",
            "✅" if self.zhipu_builder else "❌",
            "✅" if self.interviewer else "❌", "✅" if settings.has_e2b else "❌ (mock)",
        )

    # ── Interview Phase ────────────────────────────────────

    async def start_interview(self, session_id: uuid.UUID) -> dict:
        """Begin the reverse interview for a session."""
        async with async_session_factory() as db:
            session = await self._get_session(db, session_id)

            # If Claude is not available, auto-generate a basic spec from the prompt
            if not self.interviewer:
                session.status = "spec_review"
                spec = RequirementSpec(
                    session_id=session_id,
                    version=1,
                    summary=session.original_prompt or "User-submitted project",
                    requirements_json={
                        "functional": [session.original_prompt or "Build the requested project"],
                        "routes_or_pages": [],
                        "data_model": [],
                        "security": [],
                        "behavior": [],
                        "technical": [],
                    },
                    interview_history=[],
                    detected_framework="unknown",
                    detected_profile="fastapi_service",
                )
                db.add(spec)
                await db.commit()

                result = {
                    "role": "system",
                    "content": "Claude is not configured — auto-generating spec from your prompt. Confirm requirements to start building.",
                    "spec_ready": True,
                }
                await event_bus.publish(InterviewMessageEvent(
                    session_id=session_id,
                    data={"role": "assistant", "content": result["content"], "spec_ready": True},
                ))
                return result

            session.status = "interviewing"
            await db.commit()

            await event_bus.publish(SessionStatusEvent(
                session_id=session_id,
                data={"status": "interviewing"},
            ))

            # Start interview based on intake mode
            result = await self.interviewer.start_interview(
                initial_prompt=session.original_prompt,
            )

            # Create initial requirement spec with interview history
            spec = RequirementSpec(
                session_id=session_id,
                version=1,
                interview_history=[result],
            )
            db.add(spec)
            await db.commit()

            await event_bus.publish(InterviewMessageEvent(
                session_id=session_id,
                data={"role": "assistant", "content": result["content"]},
            ))

            return result

    async def process_answer(self, session_id: uuid.UUID, user_answer: str) -> dict:
        """Process a user's interview answer."""
        if not self.interviewer:
            return {
                "role": "assistant",
                "content": "Claude is not configured. Please confirm the auto-generated requirements to proceed.",
                "spec_ready": False,
            }

        # Guard against concurrent processing for the same session
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        
        async with self._session_locks[session_id]:
            async with async_session_factory() as db:
                session = await self._get_session(db, session_id)

                # Get latest spec with interview history
                result = await db.execute(
                    select(RequirementSpec)
                    .where(RequirementSpec.session_id == session_id)
                    .order_by(RequirementSpec.version.desc())
                )
                spec = result.scalar_one_or_none()
                if spec is None:
                    raise ValueError("No requirement spec found for this session")

                # Add user message to history
                history = list(spec.interview_history)
                history.append({
                    "role": "user",
                    "content": user_answer,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                # Continue interview with Claude
                response = await self.interviewer.continue_interview(
                    history=history,
                    user_answer=user_answer,
                )

                # Update history with Claude's response
                history.append(response)
                spec.interview_history = history

                # If spec is ready, populate the requirements
                if response.get("spec_ready") and response.get("spec"):
                    parsed_spec = response["spec"]
                    spec.summary = parsed_spec.get("summary", "")
                    spec.requirements_json = parsed_spec.get("requirements", {})
                    spec.detected_framework = parsed_spec.get("detected_framework")
                    spec.detected_profile = parsed_spec.get("detected_profile")

                    # Capture architectural blueprint
                    spec.blueprint_json = parsed_spec.get("blueprint", {})

                    session.status = "spec_review"
                    session.profile_type = parsed_spec.get("detected_profile")

                await db.commit()

            if response.get("spec_ready"):
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": "spec_review"},
                ))

            await event_bus.publish(InterviewMessageEvent(
                session_id=session_id,
                data={"role": "assistant", "content": response["content"], "spec_ready": response.get("spec_ready")},
            ))

            return response

    # ── Build Phase ────────────────────────────────────────

    async def start_build(self, session_id: uuid.UUID) -> None:
        """Kick off parallel builds with OpenAI and DeepSeek."""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()

        async with self._session_locks[session_id]:
            async with async_session_factory() as db:
                session = await self._get_session(db, session_id)

                if session.status in {"judging", "hardening", "complete"}:
                    logger.info("Skipping build start for %s — session already in %s", session_id, session.status)
                    return

                # Get confirmed spec
                result = await db.execute(
                    select(RequirementSpec)
                    .where(RequirementSpec.session_id == session_id)
                    .where(RequirementSpec.confirmed == True)
                    .order_by(RequirementSpec.version.desc())
                )
                spec = result.scalar_one_or_none()
                if spec is None:
                    raise ValueError("No confirmed spec found")

                profile = get_profile(session.profile_type or "unsupported", blueprint=spec.blueprint_json)
                if not profile.supported:
                    session.status = "complete"
                    await db.commit()
                    await event_bus.publish(SessionStatusEvent(
                        session_id=session_id,
                        data={"status": "complete", "detail": "Unsupported profile — analysis only"},
                    ))
                    return

                session.status = "building"
                await db.commit()

            # Await directly — caller (_run_and_clear / background_tasks) already provides fire-and-forget
            await self._run_parallel_builds(session_id)

    async def _run_parallel_builds(self, session_id: uuid.UUID) -> None:
        """Execute builds — parallel if both builders available, single if not."""
        try:
            async with async_session_factory() as db:
                session = await self._get_session(db, session_id)
                result = await db.execute(
                    select(RequirementSpec)
                    .where(RequirementSpec.session_id == session_id)
                    .where(RequirementSpec.confirmed == True)
                    .order_by(RequirementSpec.version.desc())
                )
                spec = result.scalar_one_or_none()
                profile = get_profile(session.profile_type or "unsupported", blueprint=spec.blueprint_json)

            requirements = spec.requirements_json
            profile_instructions = profile.get_builder_instructions()

            # Determine which builders to run
            builders: list[tuple[str, str, object]] = [
                ("openai", settings.openai_builder_model, self.openai_builder),
            ]
            if self.deepseek_builder:
                builders.append(("deepseek", settings.deepseek_builder_model, self.deepseek_builder))
            if self.zhipu_builder:
                builders.append(("zhipu", settings.zhipu_builder_model, self.zhipu_builder))
            if self.ollama_builder:
                builders.append(("ollama", settings.ollama_builder_model, self.ollama_builder))

            mode = "parallel" if len(builders) > 1 else "single (OpenAI only)"
            await event_bus.publish(BuildProgressEvent(
                session_id=session_id,
                data={"provider": "both" if len(builders) > 1 else "openai", "status": "started", "detail": f"Build initiated — {mode}"},
            ))

            # Create sandboxes and run builds
            # Check which providers still need to build
            providers_to_build: list[tuple[str, str, object]] = []
            async with async_session_factory() as db:
                for provider, model, builder in builders:
                    existing_result = await db.execute(
                        select(BuildCandidate)
                        .where(BuildCandidate.session_id == session_id)
                        .where(BuildCandidate.provider == provider)
                    )
                    existing = existing_result.scalar_one_or_none()
                    if existing and existing.status in ("built", "complete", "failed"):
                        logger.info("Skipping %s — candidate already exists (%s)", provider, existing.status)
                    else:
                        providers_to_build.append((provider, model, builder))

            # If all providers already built, skip straight to judging
            if not providers_to_build:
                logger.info("All candidates already built for %s — skipping to judging", session_id)
                await self._judge_candidates(session_id)
                return

            tasks = []
            sandbox_ids = []
            for provider, model, builder in providers_to_build:

                # Emit "Initiating" event for each provider immediately
                await event_bus.publish(BuildProgressEvent(
                    session_id=session_id,
                    data={"provider": provider, "status": "started", "detail": f"Model {provider} initiating..."},
                ))
                await asyncio.sleep(0.05) # Pacing

                sandbox_id = await sandbox_manager.create_sandbox(profile.name, str(session_id))
                sandbox_ids.append(sandbox_id)
                
                # Wrap the builder call to emit granular updates
                async def _task_wrapper(p=provider, m=model, b=builder, sid=sandbox_id):
                    await event_bus.publish(BuildProgressEvent(
                        session_id=session_id,
                        data={"provider": p, "status": "running", "detail": f"{p}: Thinking & Coding..."},
                    ))
                    res = await b.build_from_spec(
                        requirements_json=requirements,
                        profile_type=profile.name,
                        profile_instructions=profile_instructions,
                    )
                    await event_bus.publish(BuildProgressEvent(
                        session_id=session_id,
                        data={"provider": p, "status": "running", "detail": f"{p}: Finalizing files..."},
                    ))
                    return res

                tasks.append(_task_wrapper())

            results = await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("All parallel builds completed (success/fail count: %d)", len(results))

            # Process results
            async with async_session_factory() as db:
                for idx, (provider, model, _builder) in enumerate(providers_to_build):
                    sandbox_id = sandbox_ids[idx]
                    build_result = results[idx]
                    logger.info("Processing results for builder: %s", provider)

                    if isinstance(build_result, Exception):
                        logger.error("Build failed for %s: %s", provider, build_result)
                        candidate = BuildCandidate(
                            session_id=session_id,
                            provider=provider,
                            model=model,
                            sandbox_id=sandbox_id,
                            status="failed",
                            build_log=str(build_result),
                        )
                    else:
                        files = build_result.get("files", {})
                        await sandbox_manager.upload_files(sandbox_id, files)

                        candidate = BuildCandidate(
                            session_id=session_id,
                            provider=provider,
                            model=model,
                            sandbox_id=sandbox_id,
                            status="built",
                            files_json=files,
                            build_log=build_result.get("summary", ""),
                        )

                    db.add(candidate)
                    await db.flush()

                    await event_bus.publish(CandidateReadyEvent(
                        session_id=session_id,
                        data={
                            "candidate_id": str(candidate.id),
                            "provider": provider,
                            "status": candidate.status,
                        },
                    ))

                    # Pacing to ensure SSE delivery
                    await asyncio.sleep(0.1)

                await db.commit()
                logger.info("Built candidates committed and event published for session %s", session_id)

            # Proceed to judging
            logger.info("Transitioning to Judging Phase for session %s", session_id)
            await self._judge_candidates(session_id)

        except Exception as e:
            logger.error("Build pipeline error: %s", e)
            await event_bus.publish(ErrorEvent(
                session_id=session_id,
                data={"error": str(e), "detail": "Build pipeline failed"},
            ))

    async def _judge_candidates(self, session_id: uuid.UUID) -> None:
        """Have Claude judge the two candidates."""
        async with async_session_factory() as db:
            session = await self._get_session(db, session_id)
            session.status = "judging"

            result = await db.execute(
                select(BuildCandidate)
                .where(BuildCandidate.session_id == session_id)
                .where(BuildCandidate.status == "built")
            )
            candidates = list(result.scalars().all())

            result = await db.execute(
                select(RequirementSpec)
                .where(RequirementSpec.session_id == session_id)
                .where(RequirementSpec.confirmed == True)
                .order_by(RequirementSpec.version.desc())
            )
            spec = result.scalar_one_or_none()

            if len(candidates) < 1:
                session.status = "failed"
                await db.commit()
                await event_bus.publish(ErrorEvent(
                    session_id=session_id,
                    data={"error": "No successful candidates", "detail": "Both builders failed"},
                ))
                return

            # If only one candidate OR no judge available, auto-select
            if len(candidates) == 1 or not self.judge:
                winner = candidates[0]
                winner.is_baseline = True
                winner.score = 100.0
                session.status = "hardening"
                reason = "Only one candidate" if len(candidates) == 1 else "Claude judge not configured — auto-selecting"
                await db.commit()
                await event_bus.publish(JudgeResultEvent(
                    session_id=session_id,
                    data={"winning_candidate_id": str(winner.id), "reasoning": reason, "winner": winner.provider},
                ))
                await self.start_hardening(session_id)
                return

            profile = get_profile(session.profile_type or "unsupported")

            # Pick first two candidates as A/B — works regardless of which providers ran
            cand_a = candidates[0]
            cand_b = candidates[1]

            judge_result = await self.judge.judge_candidates(
                requirements_json=spec.requirements_json,
                profile_type=profile.name,
                openai_candidate={
                    "files": cand_a.files_json,
                    "model": cand_a.model,
                    "test_results": cand_a.test_results_json,
                    "provider": cand_a.provider,
                },
                deepseek_candidate={
                    "files": cand_b.files_json,
                    "model": cand_b.model,
                    "test_results": cand_b.test_results_json,
                    "provider": cand_b.provider,
                },
            )

            # Select winner — judge returns "openai"/"deepseek" labels but we map
            # by actual provider field to handle any DB ordering or 4-provider scenario.
            winner = judge_result.get("winner", "tie")
            provider_map = {c.provider: c for c in candidates}
            winning_candidate = provider_map.get(winner) or cand_a  # fallback to first
            winning_candidate.is_baseline = True
            winning_id = winning_candidate.id

            # Save judge decision
            decision = JudgeDecision(
                session_id=session_id,
                winning_candidate_id=winning_id,
                reasoning=judge_result.get("reasoning", ""),
                scores_json=judge_result.get("scores", {}),
                criteria_json=judge_result.get("criteria", []),
            )
            db.add(decision)

            session.status = "hardening"
            await db.commit()

            await event_bus.publish(JudgeResultEvent(
                session_id=session_id,
                data={
                    "winning_candidate_id": str(winning_id),
                    "winner": winner,
                    "reasoning": judge_result.get("reasoning", ""),
                    "scores": judge_result.get("scores", {}),
                },
            ))

            await self.start_hardening(session_id)

    # ── Hardening Phase ────────────────────────────────────

    async def start_hardening(self, session_id: uuid.UUID) -> None:
        """Begin the Mark II hardening loop on the baseline candidate."""
        await self._run_hardening_loop(session_id)

    async def _run_hardening_loop(self, session_id: uuid.UUID) -> None:
        """Execute the Mark I→VII hardening loop — calls the autonomous hardening engine."""
        await hardening_service.run_hardening_loop(session_id)


    # ── Helpers ────────────────────────────────────────────

    async def restart_sandbox(self, session_id: uuid.UUID) -> None:
        """Autonomously restore a missing or expired sandbox for a session."""
        async with async_session_factory() as db:
            session = await self._get_session(db, session_id)
            
            # Find baseline candidate
            result = await db.execute(
                select(BuildCandidate)
                .where(BuildCandidate.session_id == session_id)
                .where(BuildCandidate.is_baseline == True)
            )
            baseline = result.scalar_one_or_none()
            if not baseline:
                return

            # Check if still dead (prevent redundant restarts if many clients hit at once)
            if not await sandbox_manager.is_sandbox_alive(baseline.sandbox_id):
                logger.info("Self-healing: Restarting sandbox for session %s", session_id)
                
                # Fetch confirmed spec for blueprint
                result = await db.execute(
                    select(RequirementSpec)
                    .where(RequirementSpec.session_id == session_id)
                    .where(RequirementSpec.confirmed == True)
                    .order_by(RequirementSpec.version.desc())
                )
                spec = result.scalar_one_or_none()
                
                profile, runtime_profile, startup_cmd, install_cmd, health_path = _resolve_runtime_profile(
                    session,
                    spec,
                    baseline.files_json,
                )
                if not startup_cmd:
                    logger.warning("Self-healing skipped for %s — no startup command available", session_id)
                    return
                
                # 1. Create new sandbox
                new_sandbox_id = await sandbox_manager.create_sandbox(runtime_profile.name, str(session_id))
                
                # 2. Upload files
                await sandbox_manager.upload_files(new_sandbox_id, baseline.files_json)
                
                # 3. Install Dependencies
                if install_cmd:
                    logger.info("Self-healing: Installing dependencies in sandbox %s", new_sandbox_id)
                    await sandbox_manager.install_deps(new_sandbox_id, install_cmd)
                
                # 4. Start preview
                new_url = await sandbox_manager.start_preview(
                    new_sandbox_id,
                    startup_cmd,
                    health_path=health_path,
                )
                
                # 5. Update Candidate
                baseline.sandbox_id = new_sandbox_id
                baseline.preview_url = new_url
                await db.commit()
                
                logger.info("Self-healing complete: Sandbox %s is live at %s", new_sandbox_id, new_url)
                
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": session.status, "detail": "Preview sandbox restored"},
                ))


    async def _get_session(self, db: AsyncSession, session_id: uuid.UUID) -> ProjectSession:
        result = await db.execute(
            select(ProjectSession).where(ProjectSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session is None:
            raise ValueError(f"Session {session_id} not found")
        return session


# Singleton
orchestrator = Orchestrator()
