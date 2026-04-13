"""
Mark II Studio — Profile Registry Service
Detects project profiles and provides profile instances.
"""
from __future__ import annotations

import logging

from app.profiles.base import BaseProfile
from app.profiles.fastapi_service import FastAPIServiceProfile
from app.profiles.nextjs_webapp import NextJSWebAppProfile
from app.profiles.unsupported import UnsupportedProfile
from app.profiles.dynamic_profile import DynamicProfile

logger = logging.getLogger(__name__)

# Ordered by detection priority
PROFILE_REGISTRY: list[type[BaseProfile]] = [
    FastAPIServiceProfile,
    NextJSWebAppProfile,
]


def detect_profile(files: dict[str, str]) -> BaseProfile:
    """
    Detect the project profile from a set of uploaded files.
    Returns the first matching profile, or UnsupportedProfile as fallback.
    """
    for profile_cls in PROFILE_REGISTRY:
        if profile_cls.detect(files):
            profile = profile_cls()
            logger.info("Detected profile: %s", profile.name)
            return profile

    logger.info("No supported profile detected — falling back to analysis-only")
    return UnsupportedProfile()


def get_profile(name: str, blueprint: dict | None = None) -> BaseProfile:
    """Get a profile instance by name, optionally with a blueprint."""
    if name == "dynamic_profile":
        return DynamicProfile(blueprint=blueprint)
        
    for profile_cls in PROFILE_REGISTRY:
        instance = profile_cls()
        if instance.name == name:
            return instance
    return UnsupportedProfile()


def list_profiles() -> list[dict]:
    """List all available profiles with their metadata."""
    profiles = []
    for profile_cls in PROFILE_REGISTRY:
        instance = profile_cls()
        profiles.append({
            "name": instance.name,
            "display_name": instance.display_name,
            "supported": instance.supported,
            "preview_mode": instance.preview_mode,
        })
    return profiles
