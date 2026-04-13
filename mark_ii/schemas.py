from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field


JsonMap = dict[str, Any]


class PatchOperationModel(BaseModel):
    op: Literal["replace", "insert_before", "insert_after", "delete"]
    anchor: str = Field(min_length=1)
    content: Optional[str] = None
    occurrence: int = Field(default=1, ge=1)


class PatchPlanModel(BaseModel):
    summary: str = Field(min_length=1)
    rationale: str = ""
    operations: list[PatchOperationModel] = Field(min_length=1)


@dataclass
class PhaseResult:
    phase_id: int
    name: str
    passed: bool
    critical: bool
    details: list[str] = field(default_factory=list)
    metrics: JsonMap = field(default_factory=dict)

    def to_dict(self) -> JsonMap:
        return asdict(self)


@dataclass
class SwarmReport:
    base_url: str
    passed: bool
    phases: list[PhaseResult] = field(default_factory=list)
    summary: JsonMap = field(default_factory=dict)

    def to_dict(self) -> JsonMap:
        return asdict(self)


@dataclass
class ValidationCheck:
    name: str
    passed: bool
    detail: str
    metrics: JsonMap = field(default_factory=dict)

    def to_dict(self) -> JsonMap:
        return asdict(self)


@dataclass
class PatchCandidate:
    provider: str
    model: str
    code: str
    prompt: str
    raw_response: str
    candidate_format: str
    patch_summary: Optional[str] = None
    operations_count: int = 0
    parse_note: Optional[str] = None


@dataclass
class CandidateEvaluation:
    provider: str
    model: str
    code: str
    diff: str
    lines_changed: int
    candidate_format: str = "unknown"
    patch_summary: str | None = None
    operations_count: int = 0
    checks: list[ValidationCheck] = field(default_factory=list)
    swarm_report: Optional[SwarmReport] = None
    score: float = 0.0
    accepted: bool = False
    rejection_reason: Optional[str] = None
    failure_type: Optional[str] = None
    promoted_file: Optional[str] = None

    def to_summary(self) -> JsonMap:
        return {
            "provider": self.provider,
            "model": self.model,
            "score": self.score,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
            "failure_type": self.failure_type,
            "candidate_format": self.candidate_format,
            "patch_summary": self.patch_summary,
            "operations_count": self.operations_count,
            "lines_changed": self.lines_changed,
            "checks": [check.to_dict() for check in self.checks],
            "swarm_report": self.swarm_report.to_dict() if self.swarm_report else None,
            "promoted_file": self.promoted_file,
        }
