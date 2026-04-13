"""
Mark II Studio — Ollama Builder Provider
The Personal Coder — local coding intelligence.
"""
from __future__ import annotations

import json
import logging
import httpx
from app.settings import settings

logger = logging.getLogger(__name__)

class OllamaBuilder:
    """
    Communicates with a local Ollama instance to generate code.
    Acts as the 'Personal Coder' that improves over time via fine-tuning.
    """

    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url
        self.model = settings.ollama_builder_model
        self.timeout = httpx.Timeout(settings.max_build_timeout_s)

    async def build_from_spec(
        self,
        requirements_json: dict,
        profile_type: str,
        profile_instructions: str,
    ) -> dict:
        """
        Generate a project from a requirement spec using the local model.
        """
        prompt = f"Build a {profile_type} project from these requirements.\n\n"
        prompt += f"## Requirements Spec\n{json.dumps(requirements_json, indent=2)}\n\n"
        prompt += f"## Project Profile\nFramework: {profile_type}\n{profile_instructions}\n"
        
        system_prompt = (
            "You are Mark II Studio Personal Coder — an expert software engineer. "
            "You MUST output ONLY a valid JSON object. No markdown, no explanations. "
            "For FastAPI projects, ALWAYS include CORSMiddleware configured to allow all origins ('*'). "
            "Structure:\n"
            "{\n"
            "  \"files\": { \"filename\": \"content\" },\n"
            "  \"summary\": \"...\",\n"
            "  \"dependencies\": [],\n"
            "  \"startup_command\": \"...\"\n"
            "}"
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        "stream": False,
                        "format": "json"
                    }
                )
                response.raise_for_status()
                result = response.json()
                content = result.get("message", {}).get("content", "{}")
                
                # Parse the JSON response
                build_data = json.loads(content)
                return build_data
                
        except Exception as e:
            logger.error("Ollama build failed: %s", e)
            raise e

    async def repair(
        self,
        failure_type: str,
        source_files: dict,
        failure_details: str,
        requirements_json: dict,
    ) -> dict:
        """
        Repair code based on a hardening failure.
        """
        # (Implementation similar to OpenAI/DeepSeek repair logic but via Ollama)
        # For now, keeping it minimal to favor the Build Race
        system_prompt = "You are a senior security engineer. Fix the vulnerability in the provided source code."
        prompt = (
            f"Failure: {failure_type}\nDetails: {failure_details}\n\n"
            "Source Files:\n" + json.dumps(source_files, indent=2) + "\n\n"
            "Return the complete set of corrected files in a JSON object under the 'files' key."
        )
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": prompt}
                        ],
                        "stream": False,
                        "format": "json"
                    }
                )
                response.raise_for_status()
                result = response.json()
                content = result.get("message", {}).get("content", "{}")
                return json.loads(content)
        except Exception as e:
            logger.error("Ollama repair failed: %s", e)
            return {"files": source_files, "error": str(e)}
