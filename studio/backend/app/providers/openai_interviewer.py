"""
Mark II Studio — OpenAI Interviewer Provider
Fallback reverse-interviewer when Anthropic is unavailable or overloaded.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from openai import AsyncOpenAI

from app.providers.claude_interviewer import CODE_ANALYSIS_PROMPT, INTERVIEWER_SYSTEM_PROMPT
from app.settings import settings

logger = logging.getLogger(__name__)


class OpenAIInterviewer:
    """OpenAI-powered fallback interviewer with the same contract as ClaudeInterviewer."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_interviewer_model or settings.openai_builder_model

    async def start_interview(
        self,
        initial_prompt: str | None = None,
        code_files: dict[str, str] | None = None,
    ) -> dict:
        messages = []

        if code_files:
            code_text = "\n\n".join(
                f"--- {name} ---\n{content}" for name, content in code_files.items()
            )
            user_content = CODE_ANALYSIS_PROMPT.format(code_files=code_text)
            if initial_prompt:
                user_content += f"\n\nUser's description: {initial_prompt}"
            messages.append({"role": "user", "content": user_content})
        elif initial_prompt:
            messages.append({"role": "user", "content": f"I want to build: {initial_prompt}"})
        else:
            messages.append({
                "role": "user",
                "content": "I want to start a new project. Help me define the requirements.",
            })

        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": INTERVIEWER_SYSTEM_PROMPT},
                *messages,
            ],
        )

        content = response.choices[0].message.content or ""
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

    async def continue_interview(
        self,
        history: list[dict],
        user_answer: str,
    ) -> dict:
        messages = [
            {
                "role": msg["role"],
                "content": msg["content"],
            }
            for msg in history
        ]
        messages.append({"role": "user", "content": user_answer})

        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=0.3,
            messages=[
                {"role": "system", "content": INTERVIEWER_SYSTEM_PROMPT},
                *messages,
            ],
        )

        content = response.choices[0].message.content or ""
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

    def _strip_code_fences(self, text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines:
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        return cleaned

    def _extract_spec_json(self, content: str) -> dict | None:
        try:
            parsed = json.loads(content)
            if parsed.get("spec_ready") or parsed.get("requirements"):
                return parsed
        except (json.JSONDecodeError, AttributeError):
            pass

        try:
            stripped = self._strip_code_fences(content)
            parsed = json.loads(stripped)
            if parsed.get("spec_ready") or parsed.get("requirements"):
                return parsed
        except (json.JSONDecodeError, AttributeError):
            pass

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
        spec = self._extract_spec_json(content)
        return bool(spec and (spec.get("spec_ready") or spec.get("requirements")))
