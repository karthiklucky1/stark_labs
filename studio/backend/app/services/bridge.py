"""
Mark II Studio — Bridge Service
Maps Studio models to the mark_ii core engine types.
"""
from __future__ import annotations

import sys
from typing import Any

from app.models.requirement import RequirementSpec
from app.models.session import ProjectSession
from app.settings import settings

# Ensure we can import from mark_ii
repo_root = str(settings.project_root)
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)

from mark_ii.task_spec import TaskSpec, RouteSpec

# Payment-related keywords used to select the right swarm attack profile.
# The mark_ii swarm currently only implements "payment_api" attacks; all other
# FastAPI apps get that profile too until a generic profile is added.
_PAYMENT_KEYWORDS = {"payment", "transaction", "transfer", "balance", "wallet", "charge", "invoice"}


def _derive_attack_profile(summary: str, routes: list) -> str:
    """Pick the closest swarm attack profile based on spec content."""
    summary_lower = summary.lower()
    if any(kw in summary_lower for kw in _PAYMENT_KEYWORDS):
        return "payment_api"
    route_paths = " ".join(
        r["path"] if isinstance(r, dict) else str(r) for r in routes
    ).lower()
    if any(kw in route_paths for kw in _PAYMENT_KEYWORDS):
        return "payment_api"
    # Fallback: the Mark II core currently has a robust "payment_api" profile.
    # We use this as the primary stress test for all FastAPI apps until more
    # specialized profiles (e.g. "websocket_swarm") are added.
    return "payment_api"


def map_requirement_to_task_spec(session: ProjectSession, spec: RequirementSpec) -> TaskSpec:
    """
    Converts a Studio database requirement spec into a mark_ii TaskSpec.
    """
    reqs = spec.requirements_json
    raw_routes = reqs.get("routes_or_pages", [])

    # Map routes
    routes = []
    for r in raw_routes:
        if isinstance(r, dict) and "path" in r and "methods" in r:
            # Normalize methods for Pydantic Literal
            normalized_methods = []
            for m in r["methods"]:
                m_upper = str(m).upper()
                if m_upper in ["WEBSOCKET", "WS"]: 
                    normalized_methods.append("WEBSOCKET")
                else:
                    normalized_methods.append(m_upper)
            routes.append(RouteSpec(path=r["path"], methods=normalized_methods))
        elif isinstance(r, str):
            routes.append(RouteSpec(path=r, methods=["GET"]))

    attack_profile = _derive_attack_profile(spec.summary or "", raw_routes)

    # TaskSpec.framework is currently a single-value Literal; keep it aligned.
    framework = "fastapi_single_file"

    return TaskSpec(
        task_name=f"StudioSession_{session.id.hex[:8]}",
        description=spec.summary or "Mark II Studio session",
        framework=framework,
        attack_profile=attack_profile,
        required_routes=routes,
        smoke_steps=[],
        security_requirements=reqs.get("security", []),
        behavior_requirements=reqs.get("behavior", []),
        technical_requirements=reqs.get("technical", []),
        context={
            "session_id": str(session.id),
            "profile_type": session.profile_type,
        },
    )


def map_swarm_report_to_db(report: Any) -> dict:
    """Converts a mark_ii SwarmReport back to a plain dict for JSON storage."""
    if hasattr(report, "to_dict"):
        return report.to_dict()
    return {"raw": str(report)}
