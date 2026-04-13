from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field

from .config import DEFAULT_TASK_SPEC_FILE, MARK_II_DIR


JsonMap = dict[str, Any]


class RouteSpec(BaseModel):
    path: str = Field(min_length=1)
    methods: list[Literal["GET", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"]] = Field(min_length=1)


class SmokeStepSpec(BaseModel):
    name: str = Field(min_length=1)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "WEBSOCKET"]
    path: str = Field(min_length=1)
    json_body: Optional[JsonMap] = None
    headers: JsonMap = Field(default_factory=dict)
    expected_statuses: list[int] = Field(default_factory=lambda: [200], min_length=1)
    expect_json_field: Optional[str] = None
    expect_json_type: Optional[Literal["number", "string", "boolean", "object", "array"]] = None
    expect_json_equals: Optional[Any] = None
    save_metric_as: Optional[str] = None


class TaskSpec(BaseModel):
    task_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    framework: Literal["fastapi_single_file"] = "fastapi_single_file"
    attack_profile: str = "payment_api"
    source_file: Optional[str] = None
    bootstrap_prompt: Optional[str] = None
    required_routes: list[RouteSpec] = Field(default_factory=list)
    smoke_steps: list[SmokeStepSpec] = Field(default_factory=list)
    security_requirements: list[str] = Field(default_factory=list)
    behavior_requirements: list[str] = Field(default_factory=list)
    technical_requirements: list[str] = Field(default_factory=list)
    context: JsonMap = Field(default_factory=dict)

    @property
    def default_source_path(self) -> Optional[Path]:
        if not self.source_file:
            return None
        candidate = Path(self.source_file)
        if candidate.is_absolute():
            return candidate
        return (MARK_II_DIR / candidate).resolve()


def resolve_task_spec_path(task_spec_path: Optional[str]) -> Path:
    if task_spec_path:
        path = Path(task_spec_path)
        if path.is_absolute():
            return path
        return path.resolve()
    return DEFAULT_TASK_SPEC_FILE


def load_task_spec(task_spec_path: Optional[Union[str, Path]] = None) -> TaskSpec:
    path = resolve_task_spec_path(str(task_spec_path) if task_spec_path is not None else None)
    payload = json.loads(path.read_text())
    spec = TaskSpec.model_validate(payload)
    spec.context.setdefault("task_spec_path", str(path))
    return spec


def render_bullets(items: list[str]) -> str:
    if not items:
        return "- None specified"
    return "\n".join(f"- {item}" for item in items)


def render_routes(spec: TaskSpec) -> str:
    if not spec.required_routes:
        return "- None specified"
    return "\n".join(
        f"- {','.join(route.methods)} {route.path}"
        for route in spec.required_routes
    )


def render_smoke_steps(spec: TaskSpec) -> str:
    if not spec.smoke_steps:
        return "- None specified"

    lines: list[str] = []
    for step in spec.smoke_steps:
        body = f" json={step.json_body}" if step.json_body is not None else ""
        expect = f" expect={step.expected_statuses}"
        lines.append(f"- {step.method} {step.path}{body}{expect}")
    return "\n".join(lines)
