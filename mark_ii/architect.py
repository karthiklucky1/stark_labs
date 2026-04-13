"""
Stark Labs — Mark II Protocol
Generalized build-break-heal loop:
  1. Load a task spec that defines the API contract
  2. Start from either an existing source file or a bootstrap prompt
  3. Validate the current candidate in an isolated ASGI workspace
  4. Generate repair candidates from every configured provider
  5. Validate and score every candidate against the task spec
  6. Promote the best validated mark and repeat
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .config import MARK_II_DIR, MARK_NAMES, MAX_MARKS
from .memory import load_patch_memory, render_patch_history, save_patch_memory
from .providers import generate_patch_candidates, generate_source_candidates
from .stark_logger import log
from .task_spec import TaskSpec, load_task_spec, render_bullets, render_routes, render_smoke_steps
from .validator import rank_candidates, validate_code_snapshot

PATCH_PROMPT_TEMPLATE = """
You are J.A.R.V.I.S. — the Stark Labs Architect AI.
Task name: {task_name}
Task description:
{task_description}

The current candidate failed due to:
{failure_type}

Previous patches for this task (do not repeat these exact fixes):
{patch_history}

Required routes:
{required_routes}

Smoke expectations:
{smoke_steps}

Security requirements:
{security_requirements}

Behavior requirements:
{behavior_requirements}

Technical requirements:
{technical_requirements}

Task context:
{task_context}

Original source code:
---
{source_code}
---

Output requirements:
- Output ONLY JSON
- Return this exact shape:
  {{
    "summary": "short one-line summary of the fix",
    "rationale": "short explanation of why these edits work",
    "operations": [
      {{
        "op": "replace" | "insert_before" | "insert_after" | "delete",
        "anchor": "exact code snippet copied from the source",
        "content": "new code for replace/insert operations",
        "occurrence": 1
      }}
    ]
  }}
- Anchors must match the source code exactly
- Use multiline anchors when replacing full route bodies or validators
- Do NOT output full-file rewrites unless absolutely necessary
- Do NOT include markdown fences
"""

BOOTSTRAP_PROMPT_TEMPLATE = """
You are J.A.R.V.I.S. — the Stark Labs Builder AI.
Generate a complete single-file Python FastAPI application for this task.

Task name: {task_name}
Task description:
{task_description}

Builder request:
{builder_request}

Required routes:
{required_routes}

Smoke expectations:
{smoke_steps}

Security requirements:
{security_requirements}

Behavior requirements:
{behavior_requirements}

Technical requirements:
{technical_requirements}

Task context:
{task_context}

Output requirements:
- Output ONLY the full Python source code for one file
- Do NOT include markdown fences
- The file must expose `app = FastAPI()`
- The file must run directly with `python file.py`
"""


def _read_code(file_path: Path) -> str:
    return file_path.read_text()


def _task_spec_path(task_spec: TaskSpec) -> str | None:
    value = task_spec.context.get("task_spec_path")
    return str(value) if value else None


def _print_validation_summary(mark_name: str, evaluation) -> None:
    print(f"[MARK {mark_name}] Validation score: {evaluation.score}")
    for check in evaluation.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"  - {check.name:<7} {status} | {check.detail}")
    if evaluation.swarm_report is not None:
        for phase in evaluation.swarm_report.phases:
            verdict = "PASS" if phase.passed else "FAIL"
            print(f"  - swarm phase {phase.phase_id}: {verdict} | {phase.name}")


def _should_promote_candidate(evaluation) -> bool:
    return any(check.name == "startup" and check.passed for check in evaluation.checks)


def _render_patch_prompt(
    task_spec: TaskSpec,
    failure_type: str,
    patch_memory: list[dict],
    source_code: str,
) -> str:
    return PATCH_PROMPT_TEMPLATE.format(
        task_name=task_spec.task_name,
        task_description=task_spec.description,
        failure_type=failure_type,
        patch_history=render_patch_history(patch_memory, task_name=task_spec.task_name),
        required_routes=render_routes(task_spec),
        smoke_steps=render_smoke_steps(task_spec),
        security_requirements=render_bullets(task_spec.security_requirements),
        behavior_requirements=render_bullets(task_spec.behavior_requirements),
        technical_requirements=render_bullets(task_spec.technical_requirements),
        task_context=json.dumps(task_spec.context, indent=2, sort_keys=True),
        source_code=source_code,
    )


def _render_bootstrap_prompt(task_spec: TaskSpec, builder_request: str) -> str:
    return BOOTSTRAP_PROMPT_TEMPLATE.format(
        task_name=task_spec.task_name,
        task_description=task_spec.description,
        builder_request=builder_request,
        required_routes=render_routes(task_spec),
        smoke_steps=render_smoke_steps(task_spec),
        security_requirements=render_bullets(task_spec.security_requirements),
        behavior_requirements=render_bullets(task_spec.behavior_requirements),
        technical_requirements=render_bullets(task_spec.technical_requirements),
        task_context=json.dumps(task_spec.context, indent=2, sort_keys=True),
    )


def _save_patch_record(
    patch_memory: list[dict],
    task_spec: TaskSpec,
    mark_name: str,
    failure_type: str,
    next_file: Path,
    selected,
    ranked_candidates,
) -> None:
    patch_memory.append(
        {
            "task_name": task_spec.task_name,
            "failure_type": failure_type,
            "mark": mark_name,
            "patch_file": next_file.name,
            "accepted": selected.accepted,
            "selected_provider": selected.provider,
            "selected_model": selected.model,
            "selected_score": selected.score,
            "selected_format": selected.candidate_format,
            "selected_patch_summary": selected.patch_summary,
            "rejection_reason": selected.rejection_reason,
            "candidates": [candidate.to_summary() for candidate in ranked_candidates],
        }
    )
    save_patch_memory(patch_memory)


def _output_stem(current_file: Path, task_spec: TaskSpec) -> str:
    stem = current_file.stem
    if "_mark" in stem:
        stem = stem.split("_mark")[0]
    if stem.endswith("_bootstrap"):
        stem = stem[: -len("_bootstrap")]
    return stem or task_spec.task_name


def _next_mark_path(current_file: Path, next_mark_name: str, task_spec: TaskSpec) -> Path:
    return MARK_II_DIR / f"{_output_stem(current_file, task_spec)}_mark{next_mark_name.lower()}.py"


def _select_best_candidate(
    candidates,
    source_name: str,
    reference_code: str | None,
    task_spec: TaskSpec,
) -> tuple[list, object] | tuple[None, None]:
    evaluations = []
    for candidate in candidates:
        print(f"[ARCHITECT] Validating {candidate.provider}/{candidate.model}")
        evaluation = validate_code_snapshot(
            code=candidate.code,
            source_name=source_name,
            provider=candidate.provider,
            model=candidate.model,
            reference_code=reference_code,
            candidate_format=candidate.candidate_format,
            patch_summary=candidate.patch_summary,
            operations_count=candidate.operations_count,
            task_spec_path=_task_spec_path(task_spec),
        )
        evaluations.append(evaluation)
        print(
            f"  -> format={evaluation.candidate_format} ops={evaluation.operations_count} "
            f"score={evaluation.score} accepted={evaluation.accepted} "
            f"reason={evaluation.rejection_reason or 'passed'}"
        )

    if not evaluations:
        return None, None

    ranked = rank_candidates(evaluations)
    return ranked, ranked[0]


def _bootstrap_if_needed(
    task_spec: TaskSpec,
    source_file: str | None,
    bootstrap_prompt: str | None,
) -> Path:
    if source_file:
        return Path(source_file).resolve()

    default_source = task_spec.default_source_path
    if default_source is not None and default_source.exists():
        return default_source

    builder_request = bootstrap_prompt or task_spec.bootstrap_prompt
    if not builder_request:
        raise RuntimeError("No source file exists and no bootstrap prompt was provided")

    print(f"[BOOTSTRAP] Generating initial source for task={task_spec.task_name}")
    prompt = _render_bootstrap_prompt(task_spec, builder_request)
    candidates = asyncio.run(generate_source_candidates(prompt, task_spec.task_name))
    if not candidates:
        raise RuntimeError("No providers returned a bootstrap source candidate")

    ranked, selected = _select_best_candidate(
        candidates=candidates,
        source_name=f"{task_spec.task_name}_bootstrap.py",
        reference_code=None,
        task_spec=task_spec,
    )
    if selected is None or not _should_promote_candidate(selected):
        raise RuntimeError("No bootstrap source candidate survived startup validation")

    bootstrap_file = MARK_II_DIR / f"{task_spec.task_name}_bootstrap.py"
    bootstrap_file.write_text(selected.code)
    log(
        "bootstrap_promoted",
        task_name=task_spec.task_name,
        provider=selected.provider,
        model=selected.model,
        file=bootstrap_file.name,
        score=selected.score,
    )
    return bootstrap_file


def run_protocol(
    task_spec_path: str | None = None,
    source_file: str | None = None,
    bootstrap_prompt: str | None = None,
) -> None:
    task_spec = load_task_spec(task_spec_path)
    print("\n" + "=" * 60)
    print("  STARK LABS — MARK II PROTOCOL: INITIATED")
    print("=" * 60)
    log("protocol_start", max_marks=MAX_MARKS, task_name=task_spec.task_name)

    patch_memory = load_patch_memory()
    current_file = _bootstrap_if_needed(task_spec, source_file=source_file, bootstrap_prompt=bootstrap_prompt)

    for mark_idx in range(MAX_MARKS):
        mark_name = MARK_NAMES[mark_idx]
        print(f"\n{'─' * 60}")
        print(f"  [MARK {mark_name}] VALIDATING: {current_file.name}")
        print(f"{'─' * 60}")
        log("mark_deploy", task_name=task_spec.task_name, mark=mark_name, file=current_file.name)

        current_code = _read_code(current_file)
        baseline = validate_code_snapshot(
            code=current_code,
            source_name=current_file.name,
            provider="Baseline",
            model=current_file.name,
            task_spec_path=_task_spec_path(task_spec),
        )
        _print_validation_summary(mark_name, baseline)

        if baseline.accepted:
            print(f"\n{'=' * 60}")
            print(f"  MARK {mark_name}: INDESTRUCTIBLE. ARMOR HOLDS.")
            print(f"{'=' * 60}")
            log("mark_secure", task_name=task_spec.task_name, mark=mark_name, file=current_file.name, score=baseline.score)
            break

        failure_type = baseline.failure_type or "UNKNOWN_VULNERABILITY — validation failed"
        print(f"\n[MARK {mark_name}] DESTROYED. Failure: {failure_type}")
        log("mark_destroyed", task_name=task_spec.task_name, mark=mark_name, failure=failure_type, score=baseline.score)

        if mark_idx == MAX_MARKS - 1:
            print(f"\n[PROTOCOL] All {MAX_MARKS} marks compromised. Manual review required.")
            log("protocol_exhausted", task_name=task_spec.task_name, marks_used=MAX_MARKS)
            break

        prompt = _render_patch_prompt(
            task_spec=task_spec,
            failure_type=failure_type,
            patch_memory=patch_memory,
            source_code=current_code,
        )

        next_mark_name = MARK_NAMES[mark_idx + 1]
        print(f"\n[MARK {next_mark_name}] Summoning providers...")
        candidates = asyncio.run(generate_patch_candidates(prompt, next_mark_name, current_code))
        if not candidates:
            print("[ARCHITECT] No patch candidates were produced. Manual review required.")
            log("protocol_aborted", task_name=task_spec.task_name, reason="no_patch_candidates", mark=mark_name)
            break

        ranked, selected = _select_best_candidate(
            candidates=candidates,
            source_name=current_file.name,
            reference_code=current_code,
            task_spec=task_spec,
        )
        if selected is None or not _should_promote_candidate(selected):
            print("[ARCHITECT] No candidate survived startup validation. Manual review required.")
            log("protocol_aborted", task_name=task_spec.task_name, reason="no_startable_candidate", mark=mark_name)
            break

        next_file = _next_mark_path(current_file, next_mark_name, task_spec)
        next_file.write_text(selected.code)
        selected.promoted_file = next_file.name

        _save_patch_record(
            patch_memory=patch_memory,
            task_spec=task_spec,
            mark_name=mark_name,
            failure_type=failure_type,
            next_file=next_file,
            selected=selected,
            ranked_candidates=ranked,
        )
        log(
            "mark_promoted",
            task_name=task_spec.task_name,
            mark=next_mark_name,
            provider=selected.provider,
            model=selected.model,
            accepted=selected.accepted,
            score=selected.score,
            candidate_format=selected.candidate_format,
            file=next_file.name,
        )

        current_file = next_file
        print(
            f"\n[MARK {next_mark_name}] PROMOTED via {selected.provider}/{selected.model} "
            f"(accepted={selected.accepted}, score={selected.score})"
        )

    log("protocol_end", task_name=task_spec.task_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Mark II build-break-heal loop")
    parser.add_argument("--task-spec")
    parser.add_argument("--source-file")
    parser.add_argument("--bootstrap-prompt")
    args = parser.parse_args()

    run_protocol(
        task_spec_path=args.task_spec,
        source_file=args.source_file,
        bootstrap_prompt=args.bootstrap_prompt,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
