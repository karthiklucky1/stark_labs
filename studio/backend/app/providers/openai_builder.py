"""
Mark II Studio — OpenAI Builder Provider
GPT-5.4 as the primary code builder.
"""
from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

import sys
from app.settings import settings

# Ensure we can import from mark_ii
repo_root = str(settings.project_root)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from mark_ii.patcher import apply_patch_plan
from mark_ii.schemas import PatchPlanModel

logger = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output."""
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


BUILD_SYSTEM_PROMPT = """You are Mark II Studio Builder — an expert software engineer.
You build production-quality code from structured requirements.

Rules:
- Output ONLY the code files requested
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

## Output Format
Return a JSON object with this shape:
{{
  "files": {{
    "filename.py": "file content...",
    "requirements.txt": "dependency list...",
    ...
  }},
  "summary": "Brief description of what was built",
  "dependencies": ["dep1", "dep2"],
  "startup_command": "how to start the app"
}}
"""

PATCH_SYSTEM_PROMPT = """You are Mark II Studio Repair Engineer.
You fix code that failed validation or hardening attacks.

Rules:
- Output a JSON patch plan with targeted edits
- Use the structured patch format
- Do NOT rewrite the entire file unless absolutely necessary
- Fix ONLY the identified vulnerability or failure
"""

PATCH_PROMPT = """The project failed with:
{failure_type}

## Source Files
{source_files}

## Failure Details
{failure_details}

## Requirements
{requirements_json}

## Target File
{target_file}

## Output Format
Return a JSON object with this exact shape:
{{
  "summary": "What was fixed",
  "rationale": "Why this fix works",
  "operations": [
    {{
      "op": "replace" | "insert_before" | "insert_after" | "delete",
      "anchor": "exact code snippet from the source file",
      "content": "new code for replace/insert operations",
      "occurrence": 1
    }}
  ]
}}

Rules:
- Output ONLY JSON
- Anchors must match the source code exactly (including indentation)
- Do NOT output full file rewrites
"""


class OpenAIBuilder:
    """OpenAI GPT-5.4 code builder."""

    def __init__(self) -> None:
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_builder_model

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
            messages=[
                {"role": "system", "content": BUILD_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        raw = _strip_code_fences(response.choices[0].message.content or "")
        logger.info("OpenAI build response: %d chars", len(raw))

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.error("OpenAI returned non-JSON response")
            return {"files": {}, "summary": "Parse error", "error": raw[:500]}

    async def repair(
        self,
        failure_type: str,
        source_files: dict[str, str],
        failure_details: str,
        requirements_json: dict,
        target_file: str = "main.py",
    ) -> dict:
        """Generate a structured repair patch for failing code."""
        source_text = source_files.get(target_file, "Source missing")
        
        prompt = PATCH_PROMPT.format(
            failure_type=failure_type,
            source_files=source_text,
            failure_details=failure_details,
            requirements_json=json.dumps(requirements_json, indent=2),
            target_file=target_file,
        )
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": PATCH_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0, # Determinism for patching
            response_format={"type": "json_object"},
        )
        
        raw = _strip_code_fences(response.choices[0].message.content or "")
        try:
            plan_json = json.loads(raw)
            plan = PatchPlanModel.model_validate(plan_json)
            
            # Apply patch
            updated_code = apply_patch_plan(source_text, plan)
            
            # Update the file set
            new_files = dict(source_files)
            new_files[target_file] = updated_code
            
            return {
                "files": new_files,
                "summary": plan.summary,
                "rationale": plan.rationale,
                "operations_count": len(plan.operations),
                "patch_plan": plan_json,
            }
        except Exception as e:
            logger.error("OpenAI failed to generate valid patch: %s", e)
            # Placeholder for fallback logic — in production we might trigger a full rewrite
            return {"files": source_files, "summary": "Repair failed", "error": str(e)}
