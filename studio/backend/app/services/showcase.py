"""
Mark II Studio — Showcase Service (Project Chronicle)
Autonomous generation of marketing narratives and interactive demo scripts.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.session import ProjectSession
from app.models.candidate import BuildCandidate
from app.models.showcase import SessionShowcase
from app.settings import settings

logger = logging.getLogger(__name__)

CHRONICLE_SYSTEM_PROMPT = """You are Mark II Studio's Master Publicist — an expert at technical marketing and product storytelling in the vein of Stark Industries.

Your goal is to transform a coding project into a premium "Innovation Showcase."

Tasks:
1. TITLE: Create a compelling, high-tech project name if one isn't clear.
2. MARKETING PITCH: Write a 2-3 paragraph "Mission Briefing" that highlights the technical complexity and impact of the project. Focus on engineering excellence.
3. DEMO SCRIPT: Generate a sequence of 3-5 UI interactions to demonstrate the project. 
   - If it's a web app/game: specify CSS selectors and actions (click, type, wait).
   - If it's an API: specify endpoints and payloads for the playground.

Output EXACTLY this JSON:
{
  "title": "Project [Name]",
  "marketing_pitch": "The narrative text...",
  "demo_script": [
    {
      "action": "click" | "type" | "wait" | "api_call",
      "target": "#selector" | "/endpoint",
      "value": "text to type if applicable",
      "caption": "What is happening in this step?",
      "delay": 2000
    }
  ],
  "highlights": {
    "feature_a": "summary of feature",
    "stark_score_note": "A note on performance/hardening"
  }
}
"""

class ShowcaseService:
    """Service to handle autonomous project showcase generation."""

    async def _get_latest_baseline_candidate(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> Optional[BuildCandidate]:
        result = await db.execute(
            select(BuildCandidate)
            .where(BuildCandidate.session_id == session_id)
            .where(BuildCandidate.is_baseline == True)
            .order_by(
                BuildCandidate.updated_at.desc(),
                BuildCandidate.created_at.desc(),
                BuildCandidate.id.desc(),
            )
            .limit(1)
        )
        return result.scalars().first()

    async def _get_latest_showcase(
        self,
        db: AsyncSession,
        session_id: uuid.UUID,
    ) -> Optional[SessionShowcase]:
        result = await db.execute(
            select(SessionShowcase)
            .where(SessionShowcase.session_id == session_id)
            .order_by(SessionShowcase.created_at.desc(), SessionShowcase.id.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def generate_showcase(self, session_id: uuid.UUID) -> Optional[SessionShowcase]:
        """
        Analyze the baseline candidate and generate a premium showcase.
        """
        async with async_session_factory() as db:
            session_result = await db.execute(
                select(ProjectSession).where(ProjectSession.id == session_id)
            )
            session = session_result.scalar_one_or_none()
            if not session:
                return None

            # Get the baseline candidate (the one being showcased)
            candidate = await self._get_latest_baseline_candidate(db, session_id)
            if not candidate:
                logger.warning("No baseline candidate found for showcase generation in session %s", session_id)
                return None

            # 1. Call Claude to generate the Chronicle
            chronicle_data = await self._call_stark_publicist(session, candidate)
            
            # 2. Persist the showcase
            showcase = await self._get_latest_showcase(db, session_id)
            if showcase is None:
                showcase = SessionShowcase(session_id=session_id, is_public=True)
                db.add(showcase)

            showcase.title = chronicle_data.get("title", "Unnamed Innovation")
            showcase.marketing_pitch = chronicle_data.get("marketing_pitch", "")
            showcase.demo_script_json = chronicle_data.get("demo_script", [])
            showcase.telemetry_highlights_json = chronicle_data.get("highlights", {})
            showcase.is_public = True
            await db.commit()
            await db.refresh(showcase)
            
            logger.info("Generated Project Chronicle for session %s: %s", session_id, showcase.title)
            return showcase

    async def _call_stark_publicist(self, session: ProjectSession, candidate: BuildCandidate) -> dict:
        """Helper to invoke Claude for the marketing narrative."""
        try:
            from anthropic import AsyncAnthropic
            client = AsyncAnthropic(api_key=settings.anthropic_api_key)
            
            # Prepare context
            files_summary = "\n".join([f"- {path}" for path in candidate.files_json.keys()])
            prompt = f"""Generate a Project Chronicle for:
Original Prompt: {session.original_prompt}
Profile: {session.profile_type}
Files Built:
{files_summary}

Example code snippet (main logic):
{json.dumps(candidate.files_json.get('app/main.py') or candidate.files_json.get('src/app/page.tsx') or list(candidate.files_json.values())[0])[:3000]}
"""

            response = await client.messages.create(
                model=settings.claude_judge_model or "claude-sonnet-4-20250514",
                max_tokens=4096,
                temperature=0.7,
                system=CHRONICLE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            
            content = response.content[0].text
            # Simple JSON extraction
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            return json.loads(content)
        except Exception as e:
            logger.error("Failed to generate showcase via Claude: %s", e)
            return {
                "title": "Autonomous Project Build",
                "marketing_pitch": "A high-performance codebase generated and hardened by Mark II Studio.",
                "demo_script": [],
                "highlights": {}
            }

# Singleton
showcase_service = ShowcaseService()
