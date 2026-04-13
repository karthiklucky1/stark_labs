"""
Mark II Studio — Zhipu AI Builder Provider
GLM-4 as an alternative code builder (OpenAI-compatible API).
"""
from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from app.settings import settings

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json(text: str) -> str | None:
    """Extract the first valid JSON object from text."""
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
            return text[index: index + end]
        except json.JSONDecodeError:
            continue
    return None


BUILD_SYSTEM_PROMPT = """You are Mark II Studio Builder — an expert software engineer.
You build production-quality code from structured requirements.

CRITICAL: You MUST output ONLY a valid JSON object. No markdown, no explanations outside JSON.

Rules:
- Output ONLY a JSON object (no fences, no text before/after)
- Use best practices for the target framework
- Include all necessary imports and dependencies
- Add proper error handling and validation
- Follow the project profile conventions exactly
- Use standard typing.Union instead of | for return type hints (for maximum compatibility)
- IMPORTANT: If a route returns HTMLResponse or FileResponse, set response_model=None in the decorator to avoid Pydantic validation errors
- IMPORTANT: For FastAPI projects, ALWAYS include CORSMiddleware configured to allow all origins ('*') so the Studio UI can interact with it
- Do NOT include markdown fences or explanations outside the code
"""

BUILD_FROM_SPEC_PROMPT = """Build a {profile_type} project from these requirements.

## Requirements Spec
{requirements_json}

## Project Profile
Framework: {profile_type}
{profile_instructions}

## REQUIRED Output Format (JSON only, no other text)
{{
  "files": {{
    "filename.py": "file content...",
    "requirements.txt": "dependency list...",
  }},
  "summary": "Brief description of what was built",
  "dependencies": ["dep1", "dep2"],
  "startup_command": "how to start the app"
}}
"""

PATCH_PROMPT = """Fix code that failed with:
{failure_type}

## Source Files
{source_files}

## Failure Details
{failure_details}

## Requirements
{requirements_json}

## REQUIRED Output Format (JSON only, no other text)
{{
  "files": {{
    "filename.py": "complete fixed file content..."
  }},
  "summary": "What was fixed",
  "rationale": "Why this fix works"
}}
"""


class ZhipuBuilder:
    """Zhipu AI GLM code builder."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.zhipu_api_key,
            base_url=settings.zhipu_base_url,
        )
        self.model = settings.zhipu_builder_model

    async def build_from_spec(
        self,
        requirements_json: dict,
        profile_type: str,
        profile_instructions: str,
    ) -> dict:
        """Generate a complete project from a requirement spec."""
        prompt = BUILD_FROM_SPEC_PROMPT.format(
            profile_type=profile_type,
            requirements_json=json.dumps(requirements_json, indent=2),
            profile_instructions=profile_instructions,
        )
        response = await self.client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": BUILD_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            timeout=120.0,
        )

        raw = _strip_code_fences(response.choices[0].message.content or "")
        logger.info("Zhipu build response: %d chars", len(raw))

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            extracted = _extract_json(raw)
            if extracted:
                return json.loads(extracted)
            logger.error("Zhipu returned non-JSON response: %s", raw[:500])
            raise RuntimeError(f"Zhipu failed to generate valid JSON. Response starts with: {raw[:100]}")

    async def repair(
        self,
        failure_type: str,
        source_files: dict[str, str],
        failure_details: str,
        requirements_json: dict,
    ) -> dict:
        """Generate a repair patch for failing code."""
        source_text = "\n\n".join(
            f"--- {name} ---\n{content}" for name, content in source_files.items()
        )
        prompt = PATCH_PROMPT.format(
            failure_type=failure_type,
            source_files=source_text,
            failure_details=failure_details,
            requirements_json=json.dumps(requirements_json, indent=2),
        )
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": BUILD_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=120.0,
        )
        raw = _strip_code_fences(response.choices[0].message.content or "")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            extracted = _extract_json(raw)
            if extracted:
                return json.loads(extracted)
            return {"files": {}, "summary": "Parse error", "error": raw[:500]}
