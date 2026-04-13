from __future__ import annotations

import asyncio

from openai import AsyncOpenAI

from .config import (
    ANTHROPIC_KEY,
    ANTHROPIC_PATCH_MODEL,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_KEY,
    DEEPSEEK_PATCH_MODEL,
    OPENAI_KEY,
    OPENAI_PATCH_MODEL,
)
from .patcher import (
    PatchApplicationError,
    build_patch_candidate,
    build_source_candidate,
)
from .schemas import PatchCandidate
from .stark_logger import log


def _strip_code_fences(text: str) -> str:
    cleaned = text.strip()
    if not cleaned.startswith("```"):
        return cleaned

    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


async def _ask_openai(prompt: str, mode: str) -> str:
    client = AsyncOpenAI(api_key=OPENAI_KEY)
    kwargs = {
        "model": OPENAI_PATCH_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    if mode == "patch":
        kwargs["response_format"] = {"type": "json_object"}
    response = await client.chat.completions.create(**kwargs)
    return _strip_code_fences(response.choices[0].message.content or "")


async def _ask_anthropic(prompt: str, mode: str) -> str:
    try:
        from anthropic import AsyncAnthropic
    except ImportError as error:
        raise RuntimeError("anthropic package is not installed") from error

    client = AsyncAnthropic(api_key=ANTHROPIC_KEY)
    response = await client.messages.create(
        model=ANTHROPIC_PATCH_MODEL,
        max_tokens=6000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [block.text for block in response.content if getattr(block, "type", "") == "text"]
    return _strip_code_fences("\n".join(text_blocks))


async def _ask_deepseek(prompt: str, mode: str) -> str:
    client = AsyncOpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE_URL)
    kwargs = {
        "model": DEEPSEEK_PATCH_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    if mode == "patch":
        kwargs["response_format"] = {"type": "json_object"}
    response = await client.chat.completions.create(**kwargs)
    return _strip_code_fences(response.choices[0].message.content or "")


def _configured_providers(prompt: str, mode: str) -> list[tuple[str, str, object]]:
    providers: list[tuple[str, str, object]] = []
    if OPENAI_KEY:
        providers.append(("OpenAI", OPENAI_PATCH_MODEL, _ask_openai(prompt, mode)))
    if ANTHROPIC_KEY:
        providers.append(("Anthropic", ANTHROPIC_PATCH_MODEL, _ask_anthropic(prompt, mode)))
    if DEEPSEEK_KEY:
        providers.append(("DeepSeek-Cloud", DEEPSEEK_PATCH_MODEL, _ask_deepseek(prompt, mode)))
    if not providers:
        raise RuntimeError(
            "No providers configured. Set OPENAI_API_KEY, ANTHROPIC_API_KEY, and/or DEEPSEEK_API_KEY in .env"
        )
    return providers


async def generate_patch_candidates(prompt: str, mark_name: str, source_code: str) -> list[PatchCandidate]:
    providers = _configured_providers(prompt, mode="patch")
    log("architect_race", mark=mark_name, providers=[name for name, _, _ in providers])
    results = await asyncio.gather(*(task for _, _, task in providers), return_exceptions=True)

    candidates: list[PatchCandidate] = []
    for (provider, model, _), result in zip(providers, results):
        if isinstance(result, Exception):
            log("provider_error", provider=provider, model=model, error=str(result))
            continue
        if not result.strip():
            log("provider_error", provider=provider, model=model, error="empty_response")
            continue
        try:
            candidate = build_patch_candidate(
                provider=provider,
                model=model,
                prompt=prompt,
                response_text=result,
                source_code=source_code,
            )
        except (PatchApplicationError, ValueError) as error:
            log("provider_error", provider=provider, model=model, error=f"patch_parse_failed: {error}")
            continue
        candidates.append(candidate)
        log(
            "patch_generated",
            provider=provider,
            model=model,
            mark=mark_name,
            candidate_format=candidate.candidate_format,
            operations_count=candidate.operations_count,
        )

    return candidates


async def generate_source_candidates(prompt: str, task_name: str) -> list[PatchCandidate]:
    providers = _configured_providers(prompt, mode="build")
    log("architect_bootstrap", task_name=task_name, providers=[name for name, _, _ in providers])
    results = await asyncio.gather(*(task for _, _, task in providers), return_exceptions=True)

    candidates: list[PatchCandidate] = []
    for (provider, model, _), result in zip(providers, results):
        if isinstance(result, Exception):
            log("provider_error", provider=provider, model=model, error=str(result))
            continue
        if not result.strip():
            log("provider_error", provider=provider, model=model, error="empty_response")
            continue
        try:
            candidate = build_source_candidate(
                provider=provider,
                model=model,
                prompt=prompt,
                response_text=result,
            )
        except (PatchApplicationError, ValueError) as error:
            log("provider_error", provider=provider, model=model, error=f"source_parse_failed: {error}")
            continue
        candidates.append(candidate)
        log(
            "source_generated",
            provider=provider,
            model=model,
            task_name=task_name,
            candidate_format=candidate.candidate_format,
        )

    return candidates
