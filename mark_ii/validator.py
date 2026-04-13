from __future__ import annotations

import difflib
import tempfile
from pathlib import Path

from .runner import (
    run_candidate_smoke_suite,
    run_candidate_swarm_report,
    run_openapi_check,
    run_startup_check,
    run_syntax_check,
)
from .schemas import CandidateEvaluation, ValidationCheck
from .stark_logger import log

PHASE_FAILURE_TYPES = {
    1: "RACE_CONDITION — concurrent writes caused double-spending (balance went sub-zero)",
    2: "PAYLOAD_INJECTION — malformed or malicious input caused a 500 / server crash",
    3: "BOUNDARY_VIOLATION — server accepted negative/zero amounts (no input validation)",
    4: "ENDPOINT_FLOOD — concurrent reset+transfer race corrupted account state",
    5: "MALFORMED_JSON — invalid JSON caused a parser failure or server error",
    6: "PATH_PROBE — unusual path identifiers caused a server error",
}


def _build_diff(before: str, after: str, file_name: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"{file_name}:before",
            tofile=f"{file_name}:after",
            lineterm="",
        )
    )


def _count_changed_lines(diff: str) -> int:
    total = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+") or line.startswith("-"):
            total += 1
    return total


def _classify_failure(evaluation: CandidateEvaluation) -> tuple[str, str]:
    for check in evaluation.checks:
        if check.passed:
            continue
        if check.name == "syntax":
            return "SERVER_CRASH — generated code failed syntax validation", check.detail
        if check.name == "startup":
            return "SERVER_CRASH — generated code crashed on startup", check.detail
        if check.name == "openapi":
            return "API_SCHEMA_REGRESSION — generated patch removed required routes or schema", check.detail
        if check.name == "smoke":
            return "FUNCTIONAL_REGRESSION — generated patch broke core API behavior", check.detail
        if check.name == "swarm" and evaluation.swarm_report is not None:
            for phase in evaluation.swarm_report.phases:
                if phase.critical:
                    return PHASE_FAILURE_TYPES.get(phase.phase_id, "UNKNOWN_VULNERABILITY — swarm detected a critical failure"), phase.details[0] if phase.details else check.detail
            return "UNKNOWN_VULNERABILITY — swarm detected a critical failure", check.detail
    return "UNKNOWN_VULNERABILITY — validation ended without a clear failure", "Unknown failure"


def _score_candidate(evaluation: CandidateEvaluation) -> float:
    score = 0.0
    check_weights = {
        "syntax": 20.0,
        "startup": 15.0,
        "openapi": 10.0,
        "smoke": 20.0,
        "swarm": 35.0,
    }
    for check in evaluation.checks:
        if check.passed:
            score += check_weights.get(check.name, 0.0)

    if evaluation.swarm_report is not None and evaluation.swarm_report.phases:
        passed_phases = sum(1 for phase in evaluation.swarm_report.phases if phase.passed)
        score += passed_phases * 2.5

    if evaluation.candidate_format == "structured_patch":
        score += 5.0
    elif evaluation.candidate_format == "raw_code_fallback":
        score -= 5.0

    score -= evaluation.operations_count * 0.3
    score -= min(evaluation.lines_changed, 200) * 0.05
    return round(max(score, 0.0), 2)


def validate_code_snapshot(
    code: str,
    source_name: str,
    provider: str,
    model: str,
    reference_code: str | None = None,
    candidate_format: str = "unknown",
    patch_summary: str | None = None,
    operations_count: int = 0,
    task_spec_path: str | None = None,
) -> CandidateEvaluation:
    diff = _build_diff(reference_code or code, code, source_name) if reference_code is not None else ""
    evaluation = CandidateEvaluation(
        provider=provider,
        model=model,
        code=code,
        diff=diff,
        lines_changed=_count_changed_lines(diff),
        candidate_format=candidate_format,
        patch_summary=patch_summary,
        operations_count=operations_count,
    )

    with tempfile.TemporaryDirectory(prefix="markii_candidate_") as tempdir:
        candidate_path = Path(tempdir) / source_name
        candidate_path.write_text(code)

        syntax_ok, syntax_detail = run_syntax_check(candidate_path)
        evaluation.checks.append(ValidationCheck(name="syntax", passed=syntax_ok, detail=syntax_detail))
        if not syntax_ok:
            evaluation.failure_type, evaluation.rejection_reason = _classify_failure(evaluation)
            evaluation.score = _score_candidate(evaluation)
            log(
                "candidate_validated",
                provider=provider,
                model=model,
                accepted=False,
                score=evaluation.score,
                candidate_format=evaluation.candidate_format,
            )
            return evaluation

        startup_ok, startup_detail, startup_metrics = run_startup_check(candidate_path, task_spec_path=task_spec_path)
        evaluation.checks.append(
            ValidationCheck(name="startup", passed=startup_ok, detail=startup_detail, metrics=startup_metrics)
        )
        if not startup_ok:
            evaluation.failure_type, evaluation.rejection_reason = _classify_failure(evaluation)
            evaluation.score = _score_candidate(evaluation)
            log(
                "candidate_validated",
                provider=provider,
                model=model,
                accepted=False,
                score=evaluation.score,
                candidate_format=evaluation.candidate_format,
            )
            return evaluation

        openapi_ok, openapi_detail, openapi_metrics = run_openapi_check(candidate_path, task_spec_path=task_spec_path)
        evaluation.checks.append(
            ValidationCheck(name="openapi", passed=openapi_ok, detail=openapi_detail, metrics=openapi_metrics)
        )
        if not openapi_ok:
            evaluation.failure_type, evaluation.rejection_reason = _classify_failure(evaluation)
            evaluation.score = _score_candidate(evaluation)
            log(
                "candidate_validated",
                provider=provider,
                model=model,
                accepted=False,
                score=evaluation.score,
                candidate_format=evaluation.candidate_format,
            )
            return evaluation

        smoke_ok, smoke_detail, smoke_metrics = run_candidate_smoke_suite(candidate_path, task_spec_path=task_spec_path)
        evaluation.checks.append(
            ValidationCheck(name="smoke", passed=smoke_ok, detail=smoke_detail, metrics=smoke_metrics)
        )
        if not smoke_ok:
            evaluation.failure_type, evaluation.rejection_reason = _classify_failure(evaluation)
            evaluation.score = _score_candidate(evaluation)
            log(
                "candidate_validated",
                provider=provider,
                model=model,
                accepted=False,
                score=evaluation.score,
                candidate_format=evaluation.candidate_format,
            )
            return evaluation

        swarm_ok, swarm_report, swarm_detail = run_candidate_swarm_report(candidate_path, task_spec_path=task_spec_path)
        evaluation.swarm_report = swarm_report
        swarm_metrics = swarm_report.summary if swarm_report is not None else {}
        evaluation.checks.append(
            ValidationCheck(name="swarm", passed=swarm_ok, detail=swarm_detail, metrics=swarm_metrics)
        )

    evaluation.accepted = all(check.passed for check in evaluation.checks)
    if evaluation.accepted:
        evaluation.failure_type = None
        evaluation.rejection_reason = None
    else:
        evaluation.failure_type, evaluation.rejection_reason = _classify_failure(evaluation)
    evaluation.score = _score_candidate(evaluation)
    log(
        "candidate_validated",
        provider=provider,
        model=model,
        accepted=evaluation.accepted,
        score=evaluation.score,
        candidate_format=evaluation.candidate_format,
    )
    return evaluation


def rank_candidates(evaluations: list[CandidateEvaluation]) -> list[CandidateEvaluation]:
    return sorted(
        evaluations,
        key=lambda item: (item.accepted, item.score, -item.lines_changed),
        reverse=True,
    )
