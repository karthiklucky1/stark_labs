"""
Mark II Studio — Claude Judge Provider
Claude Sonnet 4 as the impartial judge comparing build candidates.
"""
from __future__ import annotations

import json
import logging

from anthropic import AsyncAnthropic

from app.settings import settings

logger = logging.getLogger(__name__)

JUDGE_SYSTEM_PROMPT = """You are Mark II Studio's Judge — an impartial, expert code reviewer.

Your role:
1. Compare two build candidates produced by different AI builders
2. Score each candidate against the confirmed requirements
3. Select the best candidate as the baseline for hardening
4. NEVER write code yourself — you ONLY evaluate

Evaluation criteria (weighted):
- Requirements compliance (30%): Does it implement all confirmed requirements?
- Code quality (20%): Clean, maintainable, well-structured?
- Error handling (15%): Robust error handling and validation?
- Security (15%): Input validation, auth patterns, injection prevention?
- Test readiness (10%): Is the code testable and structured for testing?
- Performance (10%): Efficient patterns, no obvious bottlenecks?

Output EXACTLY this JSON (no other text):
{
  "winner": "openai" | "deepseek" | "tie",
  "reasoning": "Detailed explanation of why the winner was chosen",
  "scores": {
    "openai": {
      "requirements_compliance": 0-10,
      "code_quality": 0-10,
      "error_handling": 0-10,
      "security": 0-10,
      "test_readiness": 0-10,
      "performance": 0-10,
      "total_weighted": 0-100
    },
    "deepseek": {
      "requirements_compliance": 0-10,
      "code_quality": 0-10,
      "error_handling": 0-10,
      "security": 0-10,
      "test_readiness": 0-10,
      "performance": 0-10,
      "total_weighted": 0-100
    }
  },
  "criteria": [
    "List of specific criteria evaluated"
  ],
  "concerns": [
    "Any concerns about either candidate that hardening should address"
  ]
}
"""

JUDGE_PROMPT = """Compare these two build candidates for the following requirements.

## Requirements Spec
{requirements_json}

## Project Profile: {profile_type}

## Candidate A — OpenAI ({openai_model})
{openai_files}

## Candidate B — DeepSeek ({deepseek_model})
{deepseek_files}

## Test Results
### OpenAI
{openai_test_results}

### DeepSeek
{deepseek_test_results}

Evaluate both candidates and select the winner.
"""

CHANGE_CLASSIFY_SYSTEM = """You are Mark II Studio's Change Analyst.
Classify user comments during build into exactly one category:

1. "direct_tweak" — Small, clear change that can be applied immediately (e.g., "make the button blue", "add a loading spinner")
2. "scope_change" — Significant change that modifies the requirement spec (e.g., "add user authentication", "switch to MongoDB")
3. "requirement_conflict" — Change that contradicts an existing confirmed requirement (e.g., "remove the login page" when auth was required)

Output EXACTLY this JSON:
{
  "classification": "direct_tweak" | "scope_change" | "requirement_conflict",
  "instruction": "Clear, structured instruction for the builder",
  "reasoning": "Why this classification was chosen",
  "affected_requirements": ["list of affected requirement IDs if applicable"],
  "requires_approval": false | true
}
"""


class ClaudeJudge:
    """Claude Sonnet 4 judge and change-request classifier."""

    def __init__(self) -> None:
        self.client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        self.model = settings.claude_judge_model

    async def judge_candidates(
        self,
        requirements_json: dict,
        profile_type: str,
        openai_candidate: dict,  # {files, model, test_results}
        deepseek_candidate: dict,
    ) -> dict:
        """Compare two candidates and select the winner."""
        openai_files = self._format_files(openai_candidate.get("files", {}))
        deepseek_files = self._format_files(deepseek_candidate.get("files", {}))

        prompt = JUDGE_PROMPT.format(
            requirements_json=json.dumps(requirements_json, indent=2),
            profile_type=profile_type,
            openai_model=openai_candidate.get("model", "unknown"),
            openai_files=openai_files,
            deepseek_model=deepseek_candidate.get("model", "unknown"),
            deepseek_files=deepseek_files,
            openai_test_results=json.dumps(openai_candidate.get("test_results", {}), indent=2),
            deepseek_test_results=json.dumps(deepseek_candidate.get("test_results", {}), indent=2),
        )

        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=0.1,
            system=JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )

        content = self._extract_text(response)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            logger.error("Judge returned non-JSON: %s", content[:200])
            return {
                "winner": "tie",
                "reasoning": "Judge output parse error",
                "scores": {},
                "criteria": [],
                "concerns": [],
            }

    async def classify_change_request(
        self,
        user_comment: str,
        requirements_json: dict,
        current_build_status: str,
    ) -> dict:
        """Classify a user's mid-build comment."""
        prompt = f"""Classify this user comment:

"{user_comment}"

Current build status: {current_build_status}

Current requirements:
{json.dumps(requirements_json, indent=2)}
"""
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            temperature=0.1,
            system=CHANGE_CLASSIFY_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )

        content = self._extract_text(response)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "classification": "direct_tweak",
                "instruction": user_comment,
                "reasoning": "Could not classify — defaulting to direct tweak",
                "affected_requirements": [],
                "requires_approval": False,
            }

    def _format_files(self, files: dict[str, str]) -> str:
        if not files:
            return "(no files)"
        sections = []
        for name, content in files.items():
            sections.append(f"### {name}\n```\n{content}\n```")
        return "\n\n".join(sections)

    def _extract_text(self, response) -> str:
        text_blocks = [
            block.text for block in response.content
            if getattr(block, "type", "") == "text"
        ]
        text = "\n".join(text_blocks).strip()
        # Strip code fences if Claude wrapped the JSON
        if text.startswith("```"):
            lines = text.splitlines()
            lines = lines[1:]  # drop opening ```
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]  # drop closing ```
            text = "\n".join(lines).strip()
        return text
