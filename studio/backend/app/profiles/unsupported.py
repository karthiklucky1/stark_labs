"""
Mark II Studio — Unsupported Profile (Analysis-Only Fallback)
Accepted intake for unrecognized project types — no autonomous build/harden.
"""
from __future__ import annotations

from typing import Any

from app.profiles.base import BaseProfile


class UnsupportedProfile(BaseProfile):
    """
    Fallback profile for projects that don't match any supported framework.
    Provides: repo analysis, gap interview, requirements summary, judge recommendations.
    Does NOT provide: autonomous build, hardening, live preview.
    """

    @property
    def name(self) -> str:
        return "unsupported"

    @property
    def display_name(self) -> str:
        return "Unsupported Project (Analysis Only)"

    @property
    def supported(self) -> bool:
        return False

    @property
    def startup_command(self) -> str:
        return ""

    @property
    def install_command(self) -> str:
        return ""

    @property
    def preview_mode(self) -> str:
        return "none"

    @property
    def hardening_suite(self) -> str:
        return "none"

    def get_builder_instructions(self) -> str:
        return """
This project uses an unsupported framework. Mark II Studio can:
- Analyze the code structure
- Interview you about requirements
- Produce a requirements spec and recommendations
- Provide a judge-level code review

Autonomous build and hardening are NOT available for this project type.
Supported profiles: fastapi_service, nextjs_webapp
"""

    def get_smoke_test_config(self) -> dict[str, Any]:
        return {}

    def get_delivery_manifest(self) -> list[str]:
        return []

    @classmethod
    def detect(cls, files: dict[str, str]) -> bool:
        # This is the fallback — always returns False since it's chosen
        # only when no other profile matches.
        return False
