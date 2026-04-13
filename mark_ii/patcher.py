from __future__ import annotations

import json

from .schemas import PatchCandidate, PatchOperationModel, PatchPlanModel


class PatchApplicationError(ValueError):
    pass


def _extract_json_object(text: str) -> str | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        return text[index : index + end]
    return None


def _find_occurrence(source_code: str, anchor: str, occurrence: int) -> int:
    start = -1
    search_from = 0
    for _ in range(occurrence):
        start = source_code.find(anchor, search_from)
        if start == -1:
            raise PatchApplicationError(f"Anchor not found for occurrence {occurrence}: {anchor[:80]!r}")
        search_from = start + len(anchor)
    return start


def _apply_operation(source_code: str, operation: PatchOperationModel) -> str:
    start = _find_occurrence(source_code, operation.anchor, operation.occurrence)
    end = start + len(operation.anchor)

    if operation.op == "replace":
        if operation.content is None:
            raise PatchApplicationError("replace operation requires content")
        return source_code[:start] + operation.content + source_code[end:]

    if operation.op == "insert_before":
        if operation.content is None:
            raise PatchApplicationError("insert_before operation requires content")
        return source_code[:start] + operation.content + source_code[start:]

    if operation.op == "insert_after":
        if operation.content is None:
            raise PatchApplicationError("insert_after operation requires content")
        return source_code[:end] + operation.content + source_code[end:]

    if operation.op == "delete":
        return source_code[:start] + source_code[end:]

    raise PatchApplicationError(f"Unsupported operation: {operation.op}")


def _looks_like_python_source(text: str) -> bool:
    markers = ("from fastapi", "import uvicorn", "app = FastAPI()", "@app.", "if __name__ == \"__main__\":")
    return any(marker in text for marker in markers)


def apply_patch_plan(source_code: str, plan: PatchPlanModel) -> str:
    updated = source_code
    for operation in plan.operations:
        updated = _apply_operation(updated, operation)
    return updated


def build_patch_candidate(
    provider: str,
    model: str,
    prompt: str,
    response_text: str,
    source_code: str,
) -> PatchCandidate:
    payload = _extract_json_object(response_text)
    if payload is not None:
        plan = PatchPlanModel.model_validate_json(payload)
        updated_code = apply_patch_plan(source_code, plan)
        return PatchCandidate(
            provider=provider,
            model=model,
            code=updated_code,
            prompt=prompt,
            raw_response=response_text,
            candidate_format="structured_patch",
            patch_summary=plan.summary,
            operations_count=len(plan.operations),
            parse_note=f"Applied {len(plan.operations)} structured operations",
        )

    if _looks_like_python_source(response_text):
        return PatchCandidate(
            provider=provider,
            model=model,
            code=response_text,
            prompt=prompt,
            raw_response=response_text,
            candidate_format="raw_code_fallback",
            patch_summary="Provider returned full source code instead of a structured patch",
            operations_count=0,
            parse_note="Used raw code fallback",
        )

    raise PatchApplicationError("Response was neither a valid patch plan nor Python source")


def build_source_candidate(
    provider: str,
    model: str,
    prompt: str,
    response_text: str,
) -> PatchCandidate:
    if not _looks_like_python_source(response_text):
        raise PatchApplicationError("Generated response did not look like Python source")

    return PatchCandidate(
        provider=provider,
        model=model,
        code=response_text,
        prompt=prompt,
        raw_response=response_text,
        candidate_format="generated_source",
        patch_summary="Provider generated an initial source file from the task prompt",
        operations_count=0,
        parse_note="Used bootstrap source generation",
    )
