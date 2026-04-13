"""
Mark II Studio — Claude Interviewer Provider
Claude Sonnet 4 as the reverse-interviewer and requirements owner.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from anthropic import AsyncAnthropic

from app.settings import settings

logger = logging.getLogger(__name__)

INTERVIEWER_SYSTEM_PROMPT = """You are Mark II Studio's Lead Architect — an expert product and systems engineer.

Your role:
1. Conduct a reverse interview with the user to extract full, unambiguous product requirements.
2. Ask targeted follow-up questions until you have enough detail to produce a complete technical specification and architectural blueprint.
3. For code intake: analyze the uploaded code first, then only ask about gaps and ambiguities.
4. Produce a final structured RequirementSpec and a ProjectBlueprint when satisfied.

Interview rules:
- Ask ONE focused question at a time (max 2 related sub-questions).
- Be conversational but efficient — respect the user's time.
- Determine the optimal tech stack for the project (e.g., Next.js for web, FastAPI for APIs, Go for performance, etc.).
- Cover: functionality, UI/UX structure, data models, auth, and logic.
- If the user says "that's it" or similar, produce the spec immediately.
- Never ask about deployment infrastructure — that's handled by our E2B cloud-engine.

When you have enough info, output EXACTLY this JSON (no other text):
{
  "spec_ready": true,
  "summary": "One-paragraph summary of the project",
  "detected_framework": "e.g. nextjs, fastapi, go, node",
  "detected_profile": "dynamic_profile",
  "requirements": {
    "functional": ["requirement 1", ...],
    "routes_or_pages": [{"path": "/...", "methods": ["GET"], "description": "..."}],
    "data_model": ["entity/model descriptions"],
    "security": ["security reqs"],
    "behavior": ["behavioral reqs"],
    "technical": ["technical reqs"]
  },
  "blueprint": {
    "tech_stack": "Detailed description of technologies (e.g., Next.js 14, Tailwind CSS, Prisma)",
    "file_tree": ["list of ALL planned files with paths from root"],
    "install_command": "The command to install all dependencies (e.g., 'npm install')",
    "startup_command": "The command to run the dev server/app (e.g., 'npm run dev')",
    "preview_port": 3000,
    "instructions": "Specific instructions for the engineers (OpenAI/DeepSeek) on how to implement this specific architecture"
  }
}

If you still need more info, output a normal text message with your question.
"""

CODE_ANALYSIS_PROMPT = """Analyze the following uploaded code and identify:
1. What framework/language is used
2. What the application does
3. What routes/pages/endpoints exist
4. What's missing or could be improved
5. What requirements are unclear

Then ask the user targeted questions about the gaps.

## Uploaded Code
{code_files}
"""


class ClaudeInterviewer:
    """Claude Sonnet 4 reverse-interviewer and requirements analyst."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_interviewer_model

    async def start_interview(
        self,
        initial_prompt: str | None = None,
        code_files: dict[str, str] | None = None,
    ) -> dict:
        """
        Start a new interview.
        Returns {role, content} of Claude's first message.
        """
        messages = []

        if code_files:
            # Code intake — analyze first
            code_text = "\n\n".join(
                f"--- {name} ---\n{content}" for name, content in code_files.items()
            )
            user_content = CODE_ANALYSIS_PROMPT.format(code_files=code_text)
            if initial_prompt:
                user_content += f"\n\nUser's description: {initial_prompt}"
            messages.append({"role": "user", "content": user_content})
        elif initial_prompt:
            messages.append({
                "role": "user",
                "content": f"I want to build: {initial_prompt}",
            })
        else:
            messages.append({
                "role": "user",
                "content": "I want to start a new project. Help me define the requirements.",
            })

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.3,
            system=INTERVIEWER_SYSTEM_PROMPT,
            messages=messages,
        )

        content = self._extract_text(response)
        return {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "spec_ready": self._is_spec_ready(content),
        }

    async def continue_interview(
        self,
        history: list[dict],
        user_answer: str,
    ) -> dict:
        """
        Continue the interview with a new user answer.
        Returns {role, content, spec_ready, spec?} of Claude's response.
        """
        messages = []
        for msg in history:
            messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })
        messages.append({"role": "user", "content": user_answer})

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.3,
            system=INTERVIEWER_SYSTEM_PROMPT,
            messages=messages,
        )

        content = self._extract_text(response)
        result = {
            "role": "assistant",
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "spec_ready": self._is_spec_ready(content),
        }

        if result["spec_ready"]:
            spec = self._extract_spec_json(content)
            if spec:
                result["spec"] = spec
            else:
                result["spec_ready"] = False

        return result

    def _extract_text(self, response) -> str:
        """Extract text content from Anthropic response."""
        text_blocks = [
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        ]
        return "\n".join(text_blocks)

    def _strip_code_fences(self, text: str) -> str:
        """Strip markdown code fences (```json ... ```) from text."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            # Remove first line (```json or ```)
            if lines:
                lines = lines[1:]
            # Remove last line (```)
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned

    def _extract_spec_json(self, content: str) -> dict | None:
        """Try to parse spec JSON from content, handling markdown fences."""
        # Try raw first
        try:
            parsed = json.loads(content)
            if parsed.get("spec_ready"):
                return parsed
        except (json.JSONDecodeError, AttributeError):
            pass

        # Try stripping code fences
        try:
            stripped = self._strip_code_fences(content)
            parsed = json.loads(stripped)
            if parsed.get("spec_ready") or parsed.get("requirements"):
                return parsed
        except (json.JSONDecodeError, AttributeError):
            pass

        # Try extracting JSON from mixed content (look for first { to last })
        try:
            start = content.index("{")
            end = content.rindex("}") + 1
            parsed = json.loads(content[start:end])
            if parsed.get("spec_ready") or parsed.get("requirements"):
                return parsed
        except (ValueError, json.JSONDecodeError):
            pass

        return None

    def _is_spec_ready(self, content: str) -> bool:
        """Check if the response contains a complete spec."""
        return self._extract_spec_json(content) is not None
