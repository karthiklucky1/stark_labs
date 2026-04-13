"""
Mark II Studio — Dynamic Profile
Framework-agnostic profile that adapts its behavior based on the Project Blueprint.
"""
from __future__ import annotations

from typing import Any

from app.profiles.base import BaseProfile


class DynamicProfile(BaseProfile):
    """
    The ultimate framework-agnostic profile.
    Loads its startup/install commands and metadata directly from the blueprint.
    """

    def __init__(self, blueprint: dict | None = None):
        self._blueprint = blueprint or {}

    @property
    def name(self) -> str:
        return "dynamic_profile"

    @property
    def display_name(self) -> str:
        return self._blueprint.get("tech_stack", "Dynamic Project")

    @property
    def supported(self) -> bool:
        return True

    @property
    def startup_command(self) -> str:
        return self._blueprint.get("startup_command", "")

    @property
    def install_command(self) -> str:
        return self._blueprint.get("install_command", "")

    @property
    def preview_mode(self) -> str:
        # Intelligently determine preview mode based on tech stack
        stack = self._blueprint.get("tech_stack", "").lower()
        if any(w in stack for w in ["nextjs", "react", "html", "vue", "vite", "web"]):
            return "iframe"
        return "api_playground"

    @property
    def hardening_suite(self) -> str:
        # Default to generic web hardening if it looks like a web app
        return "generic_web"

    def get_builder_instructions(self) -> str:
        """Pass the architect's specific instructions to the builders."""
        blueprint_tree = "\n".join([f"- {f}" for f in self._blueprint.get("file_tree", [])])
        
        return f"""
Dynamic Architectural Blueprint:
STACK: {self._blueprint.get('tech_stack', 'Determined by Architect')}

PLANNED FILE TREE:
{blueprint_tree}

INSTALL COMMAND: {self._blueprint.get('install_command')}
STARTUP COMMAND: {self._blueprint.get('startup_command')}

BUILDER INSTRUCTIONS:
{self._blueprint.get('instructions', 'Implement the planned architecture with high-fidelity.')}

CRITICAL: You MUST follow the file tree exactly. Ensure all entry points match the startup command.
"""

    def get_smoke_test_config(self) -> dict[str, Any]:
        return {
            "health_endpoint": "/",
            "expected_status": 200,
            "timeout_s": 10.0,
        }

    def get_delivery_manifest(self) -> list[str]:
        return self._blueprint.get("file_tree", [])

    @classmethod
    def detect(cls, files: dict[str, str]) -> bool:
        # This profile is selected by the Architect, not by file detection.
        return False
