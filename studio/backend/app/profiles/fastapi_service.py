"""
Mark II Studio — FastAPI Service Profile
Full autonomous build+harden support for FastAPI projects.
"""
from __future__ import annotations

from typing import Any

from app.profiles.base import BaseProfile


class FastAPIServiceProfile(BaseProfile):
    """Profile for FastAPI service projects."""

    @property
    def name(self) -> str:
        return "fastapi_service"

    @property
    def display_name(self) -> str:
        return "FastAPI Service"

    @property
    def supported(self) -> bool:
        return True

    @property
    def startup_command(self) -> str:
        return "uvicorn main:app --host 0.0.0.0 --port 8000"

    @property
    def install_command(self) -> str:
        return "pip install -r requirements.txt"

    @property
    def preview_mode(self) -> str:
        return "api_playground"

    @property
    def hardening_suite(self) -> str:
        return "fastapi_service"

    def get_builder_instructions(self) -> str:
        return """
FastAPI Service Profile Requirements:
- Use FastAPI with Pydantic v2 models
- Expose `app = FastAPI()` at module level
- Include a requirements.txt with all dependencies
- Add proper input validation with Pydantic field_validator
- Use asyncio.Lock for concurrent state mutations
- Include health check endpoint at GET /health
- Return proper HTTP status codes (422 for validation, 404 for not found, etc.)
- Include error handlers for common exceptions
- Add rate limiting for critical endpoints
- The main file must be named main.py
- Include a startup script: `if __name__ == "__main__": uvicorn.run(app, host="0.0.0.0", port=8000)`
"""

    def get_smoke_test_config(self) -> dict[str, Any]:
        return {
            "health_endpoint": "/health",
            "expected_status": 200,
            "timeout_s": 5.0,
        }

    def get_delivery_manifest(self) -> list[str]:
        return [
            "main.py",
            "requirements.txt",
            "README.md",
        ]

    @classmethod
    def detect(cls, files: dict[str, str]) -> bool:
        """Detect FastAPI projects by looking for framework markers."""
        for content in files.values():
            if "fastapi" in content.lower() and "app" in content.lower():
                return True
            if "from fastapi" in content or "import fastapi" in content:
                return True
        # Check for requirements.txt with fastapi
        req_content = files.get("requirements.txt", "")
        if "fastapi" in req_content.lower():
            return True
        return False
