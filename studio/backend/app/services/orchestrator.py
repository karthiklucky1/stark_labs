"""
Mark II Studio — Master Orchestrator
The session state machine that coordinates the entire build pipeline.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

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
from app.providers.openai_interviewer import OpenAIInterviewer
from app.providers.claude_judge import ClaudeJudge
from app.providers.ollama_builder import OllamaBuilder
from app.services.assembly import (
    build_deterministic_plan,
    build_provider_requirements,
    merge_synthesized_files,
    request_peer_review,
    request_provider_proposal,
    synthesize_master_blueprint,
)
from app.services.nextjs_repair import repair_nextjs_project_files
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


def _truncate_text(value: Any, max_chars: int = 240) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}... [truncated]"


def _compact_json(value: Any, *, max_items: int = 8, max_chars: int = 240) -> Any:
    if isinstance(value, dict):
        items = list(value.items())
        compacted = {
            key: _compact_json(item, max_items=max_items, max_chars=max_chars)
            for key, item in items[:max_items]
        }
        omitted = len(items) - max_items
        if omitted > 0:
            compacted["_omitted"] = f"{omitted} additional fields omitted"
        return compacted
    if isinstance(value, list):
        compacted = [
            _compact_json(item, max_items=max_items, max_chars=max_chars)
            for item in value[:max_items]
        ]
        omitted = len(value) - max_items
        if omitted > 0:
            compacted.append(f"... {omitted} additional items omitted")
        return compacted
    if isinstance(value, str):
        return _truncate_text(value, max_chars=max_chars)
    return value


def _builder_focus(profile_name: str, provider: str) -> list[str]:
    base_focus = [
        "Keep the project runnable immediately with complete dependencies and a valid startup command.",
        "Implement the highest-value user flow first and avoid placeholder-only files.",
        "Prefer coherent, production-style structure over unnecessary abstraction.",
    ]
    profile_specific = {
        "fastapi_service": [
            "Prioritize request validation, status codes, concurrency safety, and clear API contracts.",
            "Ensure health and core business endpoints are fully implemented and testable.",
        ],
        "nextjs_webapp": [
            "Prioritize the main UI flow, responsive layout, and clean state handling.",
            "Keep the app router structure correct and ensure the primary page works without dead links.",
        ],
    }
    provider_specific = {
        "openai": [
            "Bias toward overall product coherence and polished primary flows.",
        ],
        "deepseek": [
            "Bias toward deeper edge-case handling and stricter implementation correctness.",
        ],
        "zhipu": [
            "Bias toward form completeness, validation consistency, and solid baseline UX states.",
        ],
        "ollama": [
            "Bias toward a smaller but complete implementation with reliable local startup.",
        ],
    }
    return base_focus + profile_specific.get(profile_name, []) + provider_specific.get(provider, [])


def _compact_profile_instructions(profile_instructions: str) -> str:
    lines = [line.rstrip() for line in profile_instructions.splitlines() if line.strip()]
    if not lines:
        return ""
    limited = lines[:18]
    omitted = len(lines) - len(limited)
    text = "\n".join(limited)
    if omitted > 0:
        text += f"\n... {omitted} additional instruction lines omitted"
    return _truncate_text(text, max_chars=1800)


def _build_builder_requirements(
    spec: RequirementSpec,
    profile,
    provider: str,
) -> dict[str, Any]:
    requirements = spec.requirements_json or {}
    blueprint = spec.blueprint_json or {}
    startup_command = blueprint.get("startup_command") or profile.startup_command
    install_command = blueprint.get("install_command") or profile.install_command

    return {
        "builder_brief_version": 1,
        "project_summary": _truncate_text(spec.summary or "", max_chars=500),
        "profile_type": profile.name,
        "preview_mode": getattr(profile, "preview_mode", None),
        "implementation_focus": _builder_focus(profile.name, provider),
        "functional": _compact_json(requirements.get("functional", []), max_items=10, max_chars=220),
        "routes_or_pages": _compact_json(requirements.get("routes_or_pages", []), max_items=10, max_chars=180),
        "data_model": _compact_json(requirements.get("data_model", []), max_items=8, max_chars=200),
        "security": _compact_json(requirements.get("security", []), max_items=8, max_chars=200),
        "behavior": _compact_json(requirements.get("behavior", []), max_items=8, max_chars=200),
        "technical": _compact_json(requirements.get("technical", []), max_items=8, max_chars=200),
        "architecture": {
            "tech_stack": _truncate_text(blueprint.get("tech_stack", ""), max_chars=280),
            "install_command": install_command,
            "startup_command": startup_command,
            "preview_port": blueprint.get("preview_port"),
            "planned_files": _compact_json(blueprint.get("file_tree", []), max_items=18, max_chars=120),
            "builder_notes": _truncate_text(blueprint.get("instructions", ""), max_chars=900),
        },
    }


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
        self.fallback_interviewer = OpenAIInterviewer() if settings.openai_api_key else None
        self.judge = ClaudeJudge() if settings.has_anthropic else None
        self._session_locks: dict[uuid.UUID, asyncio.Lock] = {}

        logger.info(
            "Orchestrator ready — OpenAI=%s, DeepSeek=%s, Zhipu=%s, Claude=%s, OpenAIInterview=%s, E2B=%s",
            "✅", "✅" if self.deepseek_builder else "❌",
            "✅" if self.zhipu_builder else "❌",
            "✅" if self.interviewer else "❌",
            "✅" if self.fallback_interviewer else "❌",
            "✅" if settings.has_e2b else "❌ (mock)",
        )

    def _available_builders(self) -> dict[str, tuple[str, object]]:
        builders: dict[str, tuple[str, object]] = {
            "openai": (settings.openai_builder_model, self.openai_builder),
        }
        if self.deepseek_builder:
            builders["deepseek"] = (settings.deepseek_builder_model, self.deepseek_builder)
        if self.zhipu_builder:
            builders["zhipu"] = (settings.zhipu_builder_model, self.zhipu_builder)
        if self.ollama_builder:
            builders["ollama"] = (settings.ollama_builder_model, self.ollama_builder)
        return builders

    def get_planned_builders(self, build_mode: str | None) -> list[str]:
        mode = build_mode or "balanced"
        available = self._available_builders()
        desired_by_mode = {
            "fast": ["openai"],
            "balanced": ["openai", "deepseek"],
            "max_quality": ["openai", "deepseek", "zhipu", "ollama"],
        }
        desired = desired_by_mode.get(mode, desired_by_mode["balanced"])
        return [provider for provider in desired if provider in available]

    def _build_auto_spec_from_prompt(
        self,
        session: ProjectSession,
        *,
        user_answer: str | None = None,
    ) -> dict[str, Any]:
        prompt = (session.original_prompt or "").strip()
        detail = (user_answer or "").strip()
        combined = prompt if not detail else f"{prompt}\n\nAdditional user detail: {detail}"
        functional = [combined or "Build the requested project."]
        profile_hint = session.profile_type or "dynamic_profile"
        framework_hint = "nextjs" if "next" in combined.lower() else "unknown"
        return {
            "summary": combined[:400] or "Auto-generated project specification",
            "requirements": {
                "functional": functional,
                "routes_or_pages": [],
                "data_model": [],
                "security": [],
                "behavior": [],
                "technical": [],
            },
            "detected_framework": framework_hint,
            "detected_profile": profile_hint,
            "blueprint": {},
        }

    async def _interview_start_with_fallback(
        self,
        *,
        initial_prompt: str | None,
        code_files: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], str]:
        errors: list[str] = []
        if self.interviewer:
            try:
                return await self.interviewer.start_interview(
                    initial_prompt=initial_prompt,
                    code_files=code_files,
                ), "claude"
            except Exception as exc:
                logger.warning("Claude interviewer failed on start_interview: %s", exc)
                errors.append(f"Claude: {exc}")
        if self.fallback_interviewer:
            try:
                return await self.fallback_interviewer.start_interview(
                    initial_prompt=initial_prompt,
                    code_files=code_files,
                ), "openai"
            except Exception as exc:
                logger.warning("OpenAI interviewer failed on start_interview fallback: %s", exc)
                errors.append(f"OpenAI: {exc}")
        raise RuntimeError(" | ".join(errors) or "No interviewer available")

    async def _interview_continue_with_fallback(
        self,
        *,
        history: list[dict],
        user_answer: str,
    ) -> tuple[dict[str, Any], str]:
        errors: list[str] = []
        if self.interviewer:
            try:
                return await self.interviewer.continue_interview(
                    history=history,
                    user_answer=user_answer,
                ), "claude"
            except Exception as exc:
                logger.warning("Claude interviewer failed on continue_interview: %s", exc)
                errors.append(f"Claude: {exc}")
        if self.fallback_interviewer:
            try:
                return await self.fallback_interviewer.continue_interview(
                    history=history,
                    user_answer=user_answer,
                ), "openai"
            except Exception as exc:
                logger.warning("OpenAI interviewer failed on continue_interview fallback: %s", exc)
                errors.append(f"OpenAI: {exc}")
        raise RuntimeError(" | ".join(errors) or "No interviewer available")

    async def _persist_architecture_state(self, session_id: uuid.UUID, architecture_json: dict[str, Any]) -> None:
        async with async_session_factory() as db:
            session = await self._get_session(db, session_id)
            session.architecture_json = architecture_json
            await db.commit()

    async def _plan_architecture(
        self,
        *,
        session_id: uuid.UUID,
        spec: RequirementSpec,
        profile,
        planned_builders: list[str],
        builder_catalog: dict[str, tuple[str, object]],
    ) -> dict[str, Any]:
        base_blueprint = dict(spec.blueprint_json or {})
        deterministic_plan = build_deterministic_plan(
            profile_type=profile.name,
            base_blueprint=base_blueprint,
            planned_builders=planned_builders,
        )

        architecture_json: dict[str, Any] = {
            "version": 1,
            "protocol": "assembly_v1",
            "stage": "council",
            "council_proposals": [],
            "master_blueprint": deterministic_plan,
            "peer_reviews": [],
            "synthesis": {},
        }
        await self._persist_architecture_state(session_id, architecture_json)

        proposal_tasks = []
        for provider in planned_builders:
            proposal_tasks.append(
                request_provider_proposal(
                    provider=provider,
                    builder=builder_catalog[provider][1],
                    profile_type=profile.name,
                    requirements_json=spec.requirements_json or {},
                    base_blueprint=base_blueprint,
                    deterministic_module=deterministic_plan.get("provider_modules", {}).get(provider, {}),
                )
            )
        proposal_results = await asyncio.gather(*proposal_tasks, return_exceptions=True)
        council_proposals: list[dict[str, Any]] = []
        for provider, proposal_result in zip(planned_builders, proposal_results):
            if isinstance(proposal_result, Exception):
                logger.warning("Council proposal failed for %s: %s", provider, proposal_result)
                proposal = {
                    "summary": f"{provider} proposal failed",
                    "critical_files": [],
                    "module_boundaries": [],
                    "integration_risks": [str(proposal_result)],
                    "peer_review_focus": [],
                }
            else:
                proposal = proposal_result
            council_proposals.append(
                {
                    "provider": provider,
                    "model": builder_catalog[provider][0],
                    "proposal": proposal,
                }
            )

        master_blueprint = await synthesize_master_blueprint(
            claude_client=self.judge.client if self.judge else None,
            claude_model=self.judge.model if self.judge else None,
            profile_type=profile.name,
            requirements_json=spec.requirements_json or {},
            base_blueprint=base_blueprint,
            deterministic_plan=deterministic_plan,
            council_proposals=council_proposals,
        )
        architecture_json = {
            "version": 1,
            "protocol": "assembly_v1",
            "stage": "blueprint_complete",
            "council_proposals": council_proposals,
            "master_blueprint": master_blueprint,
            "peer_reviews": [],
            "synthesis": {},
        }
        await self._persist_architecture_state(session_id, architecture_json)
        return architecture_json

    async def _run_peer_reviews(
        self,
        *,
        master_blueprint: dict[str, Any],
        candidate_payloads: list[dict[str, Any]],
        builder_catalog: dict[str, tuple[str, object]],
    ) -> list[dict[str, Any]]:
        candidate_map = {candidate["provider"]: candidate for candidate in candidate_payloads}
        review_tasks = []
        scheduled_pairs: list[dict[str, Any]] = []
        review_pairs = master_blueprint.get("peer_review_pairs", [])
        for pair in review_pairs:
            reviewer = pair.get("reviewer")
            target = pair.get("target")
            if reviewer not in candidate_map or target not in candidate_map or reviewer not in builder_catalog:
                continue
            target_scope = master_blueprint.get("provider_modules", {}).get(target, {})
            owned_files = set(target_scope.get("owned_files", []))
            target_files = {
                path: content
                for path, content in (candidate_map[target].get("files_json") or {}).items()
                if path in owned_files
            }
            review_tasks.append(
                request_peer_review(
                    reviewer=reviewer,
                    reviewer_builder=builder_catalog[reviewer][1],
                    target=target,
                    master_blueprint=master_blueprint,
                    target_scope=target_scope,
                    target_files=target_files,
                )
            )
            scheduled_pairs.append(pair)

        if not review_tasks:
            return []

        review_results = await asyncio.gather(*review_tasks, return_exceptions=True)
        finalized: list[dict[str, Any]] = []
        for pair, review_result in zip(scheduled_pairs, review_results):
            reviewer = pair.get("reviewer")
            target = pair.get("target")
            if isinstance(review_result, Exception):
                review_payload = {
                    "verdict": "concerns",
                    "summary": f"{reviewer} review failed",
                    "critical_issues": [str(review_result)],
                    "interface_gaps": [],
                    "suggested_followups": [],
                }
            else:
                review_payload = review_result
            finalized.append({"reviewer": reviewer, "target": target, "review": review_payload})
        return finalized

    async def _score_contributors(
        self,
        *,
        session_id: uuid.UUID,
        spec: RequirementSpec,
        profile_name: str,
        candidate_payloads: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], str, list[Any]]:
        if len(candidate_payloads) == 1 or not self.judge:
            only_provider = candidate_payloads[0]["provider"]
            return (
                {only_provider: {"total_weighted": 100.0}},
                "Single contributor assembly; advisory scoring defaulted to 100.",
                ["single contributor"],
            )

        judge_result = await self.judge.judge_candidates(
            requirements_json=spec.requirements_json,
            profile_type=profile_name,
            candidates=[
                {
                    "files": payload["files_json"],
                    "model": payload["model"],
                    "test_results": payload.get("test_results_json", {}),
                    "provider": payload["provider"],
                }
                for payload in candidate_payloads
            ],
        )
        return (
            judge_result.get("scores", {}) if isinstance(judge_result.get("scores"), dict) else {},
            judge_result.get("reasoning", ""),
            judge_result.get("criteria", []),
        )

    # ── Interview Phase ────────────────────────────────────

    async def start_interview(self, session_id: uuid.UUID) -> dict:
        """Begin the reverse interview for a session."""
        async with async_session_factory() as db:
            session = await self._get_session(db, session_id)

            # If no interview providers are available, auto-generate a basic spec from the prompt
            if not self.interviewer and not self.fallback_interviewer:
                session.status = "spec_review"
                auto_spec = self._build_auto_spec_from_prompt(session)
                spec = RequirementSpec(
                    session_id=session_id,
                    version=1,
                    summary=auto_spec["summary"],
                    requirements_json=auto_spec["requirements"],
                    interview_history=[],
                    detected_framework=auto_spec["detected_framework"],
                    detected_profile=auto_spec["detected_profile"],
                    blueprint_json=auto_spec["blueprint"],
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

            try:
                result, source = await self._interview_start_with_fallback(
                    initial_prompt=session.original_prompt,
                    code_files=session.intake_files_json,
                )

                if result.get("spec_ready") and result.get("spec"):
                    parsed_spec = result["spec"]
                    session.status = "spec_review"
                    session.profile_type = parsed_spec.get("detected_profile")

                # Create initial requirement spec with interview history
                spec = RequirementSpec(
                    session_id=session_id,
                    version=1,
                    summary=parsed_spec.get("summary", "") if result.get("spec_ready") and result.get("spec") else "",
                    requirements_json=parsed_spec.get("requirements", {}) if result.get("spec_ready") and result.get("spec") else {},
                    interview_history=[result],
                    detected_framework=parsed_spec.get("detected_framework") if result.get("spec_ready") and result.get("spec") else None,
                    detected_profile=parsed_spec.get("detected_profile") if result.get("spec_ready") and result.get("spec") else None,
                    blueprint_json=parsed_spec.get("blueprint", {}) if result.get("spec_ready") and result.get("spec") else {},
                )
                db.add(spec)
                await db.commit()

                detail = "Interview started"
                if source == "openai":
                    detail = "Claude interviewer overloaded — using OpenAI fallback"
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": session.status, "detail": detail},
                ))

                await event_bus.publish(InterviewMessageEvent(
                    session_id=session_id,
                    data={"role": "assistant", "content": result["content"], "spec_ready": result.get("spec_ready")},
                ))

                return result
            except Exception as exc:
                logger.error("Interview startup failed for %s: %s", session_id, exc)
                auto_spec = self._build_auto_spec_from_prompt(session)
                session.status = "spec_review"
                spec = RequirementSpec(
                    session_id=session_id,
                    version=1,
                    summary=auto_spec["summary"],
                    requirements_json=auto_spec["requirements"],
                    interview_history=[{
                        "role": "assistant",
                        "content": "Interview services were overloaded, so Stark generated a draft spec from your prompt. Review it and continue from spec review.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "spec_ready": True,
                    }],
                    detected_framework=auto_spec["detected_framework"],
                    detected_profile=auto_spec["detected_profile"],
                    blueprint_json=auto_spec["blueprint"],
                )
                db.add(spec)
                await db.commit()

                result = {
                    "role": "assistant",
                    "content": "Interview services were overloaded, so Stark generated a draft spec from your prompt. Review it and continue from spec review.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "spec_ready": True,
                    "spec": auto_spec,
                }
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": "spec_review", "detail": "Interview overloaded — using draft spec"},
                ))
                await event_bus.publish(InterviewMessageEvent(
                    session_id=session_id,
                    data={"role": "assistant", "content": result["content"], "spec_ready": True},
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

                try:
                    # Continue interview with fallback if needed
                    response, source = await self._interview_continue_with_fallback(
                        history=history,
                        user_answer=user_answer,
                    )
                except Exception as exc:
                    logger.error("Interview continuation failed for %s: %s", session_id, exc)
                    auto_spec = self._build_auto_spec_from_prompt(session, user_answer=user_answer)
                    response = {
                        "role": "assistant",
                        "content": "Interview services were overloaded, so Stark generated a draft spec from your prompt and latest answer. Review it and continue from spec review.",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "spec_ready": True,
                        "spec": auto_spec,
                    }
                    source = "auto_spec"

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

            if source == "openai":
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": "interviewing", "detail": "Claude interviewer overloaded — using OpenAI fallback"},
                ))
            elif source == "auto_spec":
                await event_bus.publish(SessionStatusEvent(
                    session_id=session_id,
                    data={"status": "spec_review", "detail": "Interview overloaded — using draft spec"},
                ))

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

            full_requirements_size = len(str(spec.requirements_json or {}))
            compact_profile_instructions = _compact_profile_instructions(profile.get_builder_instructions())

            builder_catalog = self._available_builders()
            planned_builders = self.get_planned_builders(session.build_mode)
            builders: list[tuple[str, str, object]] = [
                (provider, builder_catalog[provider][0], builder_catalog[provider][1])
                for provider in planned_builders
            ]

            mode = session.build_mode or "balanced"
            if not builders:
                raise ValueError(f"No builders available for build mode {mode}")
            await event_bus.publish(BuildProgressEvent(
                session_id=session_id,
                data={
                    "provider": "multi" if len(builders) > 1 else builders[0][0],
                    "status": "started",
                    "detail": f"Assembly initiated — {mode.replace('_', ' ')} mode with {', '.join(planned_builders)}",
                },
            ))
            await event_bus.publish(SessionStatusEvent(
                session_id=session_id,
                data={"status": "building", "detail": "Council of Architects drafting master blueprint…"},
            ))

            architecture_json = await self._plan_architecture(
                session_id=session_id,
                spec=spec,
                profile=profile,
                planned_builders=planned_builders,
                builder_catalog=builder_catalog,
            )
            master_blueprint = architecture_json.get("master_blueprint", {})

            await event_bus.publish(SessionStatusEvent(
                session_id=session_id,
                data={"status": "building", "detail": "Master blueprint locked — modular assembly starting"},
            ))

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

            if not providers_to_build:
                logger.info("All module contributors already built for %s — skipping to synthesis", session_id)
                await self._judge_candidates(session_id)
                return

            tasks = []
            for provider, model, builder in providers_to_build:
                module_scope = master_blueprint.get("provider_modules", {}).get(provider, {})
                module_name = module_scope.get("module_name") or f"{provider.title()} module"

                await event_bus.publish(BuildProgressEvent(
                    session_id=session_id,
                    data={"provider": provider, "status": "started", "detail": f"{provider}: Owning {module_name}"},
                ))
                await asyncio.sleep(0.05)

                async def _task_wrapper(p=provider, m=model, b=builder, scope=module_scope):
                    started_at = time.perf_counter()
                    try:
                        scoped_requirements = _build_builder_requirements(spec, profile, p)
                        assembly_requirements = build_provider_requirements(
                            base_requirements=scoped_requirements,
                            master_blueprint=master_blueprint,
                            provider=p,
                        )
                        logger.info(
                            "Dispatching %s assembly brief (%d chars scoped requirements vs %d original, %d chars instructions)",
                            p,
                            len(str(assembly_requirements)),
                            full_requirements_size,
                            len(compact_profile_instructions),
                        )
                        await event_bus.publish(BuildProgressEvent(
                            session_id=session_id,
                            data={"provider": p, "status": "running", "detail": f"{p}: Building owned module surface…"},
                        ))
                        res = await b.build_from_spec(
                            requirements_json=assembly_requirements,
                            profile_type=profile.name,
                            profile_instructions=compact_profile_instructions,
                        )
                        await event_bus.publish(BuildProgressEvent(
                            session_id=session_id,
                            data={"provider": p, "status": "running", "detail": f"{p}: Packaging contribution…"},
                        ))
                        return {
                            "result": res,
                            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                            "module_scope": scope,
                        }
                    except Exception as exc:
                        return {
                            "error": str(exc),
                            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                            "module_scope": scope,
                        }

                tasks.append(_task_wrapper())

            results = await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("All modular assembly builds completed (count: %d)", len(results))

            async with async_session_factory() as db:
                for idx, (provider, model, _builder) in enumerate(providers_to_build):
                    build_result = results[idx]
                    logger.info("Processing module contributor result for builder: %s", provider)
                    module_scope = master_blueprint.get("provider_modules", {}).get(provider, {})

                    if isinstance(build_result, Exception):
                        logger.error("Build failed for %s: %s", provider, build_result)
                        candidate = BuildCandidate(
                            session_id=session_id,
                            provider=provider,
                            model=model,
                            status="failed",
                            build_log=str(build_result),
                            module_scope_json=module_scope,
                            candidate_format="assembly_contributor",
                        )
                    else:
                        duration_ms = build_result.get("duration_ms")
                        if build_result.get("error"):
                            logger.error("Build failed for %s: %s", provider, build_result["error"])
                            candidate = BuildCandidate(
                                session_id=session_id,
                                provider=provider,
                                model=model,
                                status="failed",
                                build_log=build_result["error"],
                                build_duration_ms=duration_ms,
                                module_scope_json=module_scope,
                                candidate_format="assembly_contributor",
                            )
                        else:
                            build_payload = build_result.get("result") or {}
                            files, files_changed = repair_nextjs_project_files(build_payload.get("files", {}))
                            if files_changed:
                                logger.info("Applied deterministic Next.js file repair for provider %s", provider)

                            candidate = BuildCandidate(
                                session_id=session_id,
                                provider=provider,
                                model=model,
                                status="built",
                                files_json=files,
                                build_log=build_payload.get("summary", ""),
                                build_duration_ms=duration_ms,
                                module_scope_json=module_scope,
                                candidate_format="assembly_contributor",
                            )

                    db.add(candidate)
                    await db.flush()

                    await event_bus.publish(CandidateReadyEvent(
                        session_id=session_id,
                        data={
                            "candidate_id": str(candidate.id),
                            "provider": provider,
                            "status": candidate.status,
                            "model": candidate.model,
                            "build_log": candidate.build_log,
                            "duration_ms": candidate.build_duration_ms,
                        },
                    ))
                    await asyncio.sleep(0.1)

                session = await self._get_session(db, session_id)
                architecture_json = dict(session.architecture_json or {})
                architecture_json["stage"] = "assembly_complete"
                session.architecture_json = architecture_json
                await db.commit()
                logger.info("Module contributors committed for session %s", session_id)

            logger.info("Transitioning to synthesis for session %s", session_id)
            await self._judge_candidates(session_id)

        except Exception as e:
            logger.error("Build pipeline error: %s", e)
            await event_bus.publish(ErrorEvent(
                session_id=session_id,
                data={"error": str(e), "detail": "Build pipeline failed"},
            ))

    async def _judge_candidates(self, session_id: uuid.UUID) -> None:
        """Score contributors, synthesize a baseline, and hand it off to hardening."""
        async with async_session_factory() as db:
            session = await self._get_session(db, session_id)
            session.status = "judging"
            await db.commit()

            result = await db.execute(
                select(RequirementSpec)
                .where(RequirementSpec.session_id == session_id)
                .where(RequirementSpec.confirmed == True)
                .order_by(RequirementSpec.version.desc())
            )
            spec = result.scalar_one_or_none()

            result = await db.execute(
                select(BuildCandidate)
                .where(BuildCandidate.session_id == session_id)
                .where(BuildCandidate.status == "built")
                .where(BuildCandidate.provider != "synthesis")
            )
            candidates = list(result.scalars().all())

            architecture_json = dict(session.architecture_json or {})
            profile = get_profile(session.profile_type or "unsupported", blueprint=spec.blueprint_json if spec else None)

        if len(candidates) < 1:
            async with async_session_factory() as db:
                session = await self._get_session(db, session_id)
                session.status = "failed"
                await db.commit()
            await event_bus.publish(ErrorEvent(
                session_id=session_id,
                data={"error": "No successful candidates", "detail": "All module contributors failed"},
            ))
            return

        if architecture_json.get("protocol") != "assembly_v1":
            async with async_session_factory() as db:
                session = await self._get_session(db, session_id)
                session.status = "hardening"
                result = await db.execute(
                    select(BuildCandidate).where(BuildCandidate.id == candidates[0].id)
                )
                winner = result.scalar_one()
                winner.is_baseline = True
                winner.score = 100.0
                decision = JudgeDecision(
                    session_id=session_id,
                    winning_candidate_id=winner.id,
                    reasoning="Fallback competitive flow used.",
                    scores_json={winner.provider: {"total_weighted": 100.0}},
                    criteria_json=["fallback competitive flow"],
                )
                db.add(decision)
                await db.commit()
            await event_bus.publish(JudgeResultEvent(
                session_id=session_id,
                data={
                    "winning_candidate_id": str(winner.id),
                    "winner": winner.provider,
                    "reasoning": "Fallback competitive flow used.",
                    "scores": {winner.provider: {"total_weighted": 100.0}},
                },
            ))
            await self.start_hardening(session_id)
            return

        candidate_payloads = [
            {
                "id": candidate.id,
                "provider": candidate.provider,
                "model": candidate.model,
                "files_json": dict(candidate.files_json or {}),
                "build_log": candidate.build_log,
                "module_scope_json": dict(candidate.module_scope_json or {}),
                "test_results_json": dict(candidate.test_results_json or {}),
            }
            for candidate in candidates
        ]
        master_blueprint = architecture_json.get("master_blueprint") or build_deterministic_plan(
            profile_type=profile.name,
            base_blueprint=spec.blueprint_json if spec else {},
            planned_builders=[candidate["provider"] for candidate in candidate_payloads],
        )

        await event_bus.publish(SessionStatusEvent(
            session_id=session_id,
            data={"status": "judging", "detail": "Cross-model peer review running…"},
        ))
        peer_reviews = await self._run_peer_reviews(
            master_blueprint=master_blueprint,
            candidate_payloads=candidate_payloads,
            builder_catalog=self._available_builders(),
        )

        await event_bus.publish(SessionStatusEvent(
            session_id=session_id,
            data={"status": "judging", "detail": "Final synthesis assembling baseline…"},
        ))
        scores, advisory_reasoning, criteria = await self._score_contributors(
            session_id=session_id,
            spec=spec,
            profile_name=profile.name,
            candidate_payloads=candidate_payloads,
        )

        merged = merge_synthesized_files(
            master_blueprint=master_blueprint,
            candidate_files={payload["provider"]: payload["files_json"] for payload in candidate_payloads},
            preferred_order=[payload["provider"] for payload in candidate_payloads],
        )
        synthesis_files, files_changed = repair_nextjs_project_files(merged.get("files", {}))
        if files_changed:
            logger.info("Applied deterministic Next.js file repair for synthesized baseline")

        synthesis_sandbox_id = await sandbox_manager.create_sandbox(profile.name, str(session_id))
        await sandbox_manager.upload_files(synthesis_sandbox_id, synthesis_files)

        async with async_session_factory() as db:
            session = await self._get_session(db, session_id)
            result = await db.execute(
                select(BuildCandidate)
                .where(BuildCandidate.session_id == session_id)
                .where(BuildCandidate.provider != "synthesis")
            )
            persisted_candidates = list(result.scalars().all())
            candidate_by_provider = {candidate.provider: candidate for candidate in persisted_candidates}

            for candidate in persisted_candidates:
                raw_score = None
                if isinstance(scores.get(candidate.provider), dict):
                    raw_score = scores[candidate.provider].get("total_weighted")
                try:
                    candidate.score = float(raw_score) if raw_score is not None else candidate.score
                except (TypeError, ValueError):
                    candidate.score = candidate.score
                candidate.review_notes_json = [
                    review for review in peer_reviews
                    if review.get("target") == candidate.provider
                ]
                candidate.is_baseline = False

            synthesis_candidate = BuildCandidate(
                session_id=session_id,
                provider="synthesis",
                model=self.judge.model if self.judge else "assembly_v1",
                sandbox_id=synthesis_sandbox_id,
                status="built",
                score=100.0,
                is_baseline=True,
                files_json=synthesis_files,
                build_log=merged.get("summary", "Synthesized baseline assembled from contributor modules."),
                module_scope_json={
                    "module_name": "Synthesized baseline",
                    "contributors": merged.get("contributions", {}),
                    "owned_files": master_blueprint.get("file_tree", []),
                    "source_providers": list(candidate_by_provider.keys()),
                },
                review_notes_json=peer_reviews,
                candidate_format="synthesized_baseline",
            )
            db.add(synthesis_candidate)
            await db.flush()

            architecture_json["stage"] = "synthesized"
            architecture_json["peer_reviews"] = peer_reviews
            architecture_json["synthesis"] = {
                "summary": merged.get("summary", ""),
                "contributions": merged.get("contributions", {}),
                "source_providers": list(candidate_by_provider.keys()),
            }
            session.architecture_json = architecture_json

            reasoning = "Assembly protocol merged module contributions into a single baseline for hardening."
            if advisory_reasoning:
                reasoning = f"{reasoning} {advisory_reasoning.strip()}"
            decision = JudgeDecision(
                session_id=session_id,
                winning_candidate_id=synthesis_candidate.id,
                reasoning=reasoning,
                scores_json=scores,
                criteria_json=list(criteria) + ["assembly_v1 synthesized baseline"],
            )
            db.add(decision)

            session.status = "hardening"
            await db.commit()

        await event_bus.publish(CandidateReadyEvent(
            session_id=session_id,
            data={
                "candidate_id": str(synthesis_candidate.id),
                "provider": "synthesis",
                "status": "built",
                "model": synthesis_candidate.model,
                "build_log": synthesis_candidate.build_log,
                "duration_ms": None,
            },
        ))
        await event_bus.publish(JudgeResultEvent(
            session_id=session_id,
            data={
                "winning_candidate_id": str(synthesis_candidate.id),
                "winner": "synthesis",
                "reasoning": reasoning,
                "scores": scores,
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
