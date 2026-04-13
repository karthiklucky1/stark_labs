"""
Mark II Studio — Base Profile ABC
Defines the interface every project profile must implement.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseProfile(ABC):
    """Abstract base for project profiles."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Profile identifier, e.g. 'fastapi_service'."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name, e.g. 'FastAPI Service'."""

    @property
    @abstractmethod
    def supported(self) -> bool:
        """Whether this profile supports full autonomous build+harden."""

    @property
    @abstractmethod
    def startup_command(self) -> str:
        """Command to start the app in the sandbox."""

    @property
    @abstractmethod
    def install_command(self) -> str:
        """Command to install dependencies."""

    @property
    @abstractmethod
    def preview_mode(self) -> str:
        """'iframe' for web apps, 'api_playground' for APIs."""

    @property
    @abstractmethod
    def hardening_suite(self) -> str:
        """Name of the attack suite to run."""

    @abstractmethod
    def get_builder_instructions(self) -> str:
        """Profile-specific instructions appended to builder prompts."""

    @abstractmethod
    def get_smoke_test_config(self) -> dict[str, Any]:
        """Configuration for smoke/health checks."""

    @abstractmethod
    def get_delivery_manifest(self) -> list[str]:
        """List of files/directories to include in the final delivery."""

    @classmethod
    def detect(cls, files: dict[str, str]) -> bool:
        """
        Given a set of uploaded files, return True if this profile matches.
        Subclasses override with framework-specific detection logic.
        """
        return False
