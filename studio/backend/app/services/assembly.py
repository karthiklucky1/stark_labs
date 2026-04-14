"""
Mark II Studio — Multi-Model Assembly Helpers
Blueprint council, module ownership, peer review planning, and final synthesis.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_PROVIDER_JSON_TIMEOUT_SECONDS = 45
_SYNTHESIS_TIMEOUT_SECONDS = 45

_PROPOSAL_OUTPUT_SCHEMA_JSON = json.dumps(
    {
        "summary": "Short provider-specific architecture summary",
        "critical_files": ["path"],
        "file_tree_delta": ["path"],
        "api_contracts": [
            {
                "path": "/resource",
                "methods": ["GET"],
                "purpose": "What this route or page handles",
            }
        ],
        "data_entities": [
            {
                "name": "EntityName",
                "shape": "Short summary of important fields",
            }
        ],
        "ui_surfaces": [
            {
                "surface": "Dashboard",
                "purpose": "Primary user interaction",
                "owner_hint": "provider_id",
            }
        ],
        "module_boundaries": [
            {
                "module_name": "string",
                "goal": "string",
                "suggested_owner": "provider_id",
                "files": ["path"],
                "interfaces": ["string"],
            }
        ],
        "integration_risks": ["string"],
        "peer_review_focus": ["string"],
    },
    indent=2,
)

_REVIEW_OUTPUT_SCHEMA_JSON = json.dumps(
    {
        "verdict": "approve | concerns",
        "summary": "Short review summary",
        "critical_issues": ["string"],
        "interface_gaps": ["string"],
        "suggested_followups": ["string"],
    },
    indent=2,
)

_SYNTHESIS_OUTPUT_SCHEMA_JSON = json.dumps(
    {
        "summary": "Architecture summary",
        "council_summary": ["string"],
        "shared_contracts": ["string"],
        "integration_notes": ["string"],
        "api_contracts": [
            {
                "path": "/resource",
                "methods": ["GET"],
                "purpose": "What this route or page handles",
            }
        ],
        "data_entities": [
            {
                "name": "EntityName",
                "shape": "Short summary of important fields",
            }
        ],
        "ui_surfaces": [
            {
                "surface": "Dashboard",
                "purpose": "Primary user interaction",
                "owner_hint": "provider_id",
            }
        ],
        "provider_modules": {
            "provider_id": {
                "module_name": "string",
                "responsibilities": ["string"],
                "owned_files": ["path"],
                "review_focus": ["string"],
            }
        },
    },
    indent=2,
)

_PROPOSAL_SYSTEM_PROMPT = """You are part of Stark Labs' Council of Architects.
Return ONLY valid JSON.

You are proposing a modular architecture plan, not writing code.
Be concrete about file ownership, integration risks, and interface contracts.
"""

_PROPOSAL_PROMPT = """Propose an implementation blueprint for this project.

## Profile
{profile_type}

## Requirements
{requirements_json}

## Existing Blueprint
{base_blueprint_json}

## Provider Focus
{provider_focus_json}

## Output JSON
{output_schema_json}
"""

_REVIEW_SYSTEM_PROMPT = """You are a peer-review engineer in Stark Labs' modular assembly protocol.
Return ONLY valid JSON.

Review another model's owned module for:
- contract mismatches
- logic risks
- validation/security gaps
- integration breaks
"""

_REVIEW_PROMPT = """Review this module contribution against the master blueprint.

## Reviewer
{reviewer}

## Review Target
{target}

## Master Blueprint
{master_blueprint_json}

## Target Module Scope
{module_scope_json}

## Target Files
{target_files}

## Output JSON
{output_schema_json}
"""

_SYNTHESIS_SYSTEM_PROMPT = """You are Stark Labs' synthesis lead.
Return ONLY valid JSON.

You are synthesizing multiple architecture proposals into one master blueprint.
Respect strict file ownership and produce a clean module plan for assembly.
"""

_SYNTHESIS_PROMPT = """Synthesize a single master blueprint from these architecture proposals.

## Profile
{profile_type}

## Requirements
{requirements_json}

## Base Blueprint
{base_blueprint_json}

## Deterministic Ownership Seed
{deterministic_plan_json}

## Council Proposals
{council_proposals_json}

## Output JSON
{output_schema_json}
"""


def _strip_code_fences(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned.startswith("```"):
        return cleaned
    lines = cleaned.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json(text: str) -> str | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
            return text[index:index + end]
        except json.JSONDecodeError:
            continue
    return None


def _parse_json_response(raw_text: str) -> dict[str, Any]:
    cleaned = _strip_code_fences(raw_text)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        extracted = _extract_json(cleaned)
        if extracted:
            parsed = json.loads(extracted)
            return parsed if isinstance(parsed, dict) else {}
    return {}


def _truncate_text(text: str, max_chars: int = 220) -> str:
    value = str(text or "").strip()
    if len(value) <= max_chars:
        return value
    return f"{value[:max_chars].rstrip()}... [truncated]"


def _normalize_file_tree(raw_file_tree: Any) -> list[str]:
    paths: list[str] = []
    if isinstance(raw_file_tree, list):
        for item in raw_file_tree:
            if isinstance(item, str):
                path = item.strip()
            elif isinstance(item, dict):
                path = str(item.get("path") or item.get("file") or "").strip()
            else:
                path = ""
            if path:
                paths.append(path)
    deduped = sorted({path for path in paths if path and not path.endswith("/")})
    return deduped


def _default_file_tree(profile_type: str) -> list[str]:
    if profile_type == "nextjs_webapp":
        return [
            "package.json",
            "postcss.config.js",
            "tailwind.config.js",
            "tsconfig.json",
            "next-env.d.ts",
            "app/layout.tsx",
            "app/page.tsx",
            "app/globals.css",
            "components/ApplicationForm.tsx",
            "components/ApplicationsTable.tsx",
            "components/KanbanBoard.tsx",
            "components/ApplicationDetail.tsx",
            "lib/types.ts",
            "lib/storage.ts",
            "lib/store.ts",
            "lib/filters.ts",
        ]
    if profile_type == "fastapi_service":
        return [
            "requirements.txt",
            "main.py",
            "app/models.py",
            "app/schemas.py",
            "app/services.py",
            "app/routes.py",
            "app/security.py",
            "tests/test_api.py",
        ]
    return ["README.md"]


def _normalize_methods(raw_methods: Any) -> list[str]:
    if not isinstance(raw_methods, list):
        return []
    methods: list[str] = []
    for item in raw_methods:
        value = str(item or "").strip().upper()
        if value:
            methods.append(value)
    return methods[:6]


def _normalize_api_contracts(raw_contracts: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_contracts, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in raw_contracts[:10]:
        if isinstance(item, dict):
            path = str(item.get("path") or item.get("route") or item.get("name") or "").strip()
            purpose = _truncate_text(str(item.get("purpose") or item.get("description") or ""), max_chars=140)
            methods = _normalize_methods(item.get("methods"))
            if path:
                normalized.append({
                    "path": path,
                    "methods": methods,
                    "purpose": purpose,
                })
        elif isinstance(item, str) and item.strip():
            normalized.append({"path": item.strip(), "methods": [], "purpose": ""})
    return normalized


def _normalize_data_entities(raw_entities: Any) -> list[dict[str, str]]:
    if not isinstance(raw_entities, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw_entities[:10]:
        if isinstance(item, dict):
            name = str(item.get("name") or item.get("entity") or item.get("table") or "").strip()
            shape = _truncate_text(str(item.get("shape") or item.get("fields") or item.get("description") or ""), max_chars=160)
            if name:
                normalized.append({"name": name, "shape": shape})
        elif isinstance(item, str) and item.strip():
            normalized.append({"name": item.strip(), "shape": ""})
    return normalized


def _normalize_ui_surfaces(raw_surfaces: Any) -> list[dict[str, str]]:
    if not isinstance(raw_surfaces, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in raw_surfaces[:10]:
        if isinstance(item, dict):
            surface = str(item.get("surface") or item.get("name") or item.get("page") or "").strip()
            purpose = _truncate_text(str(item.get("purpose") or item.get("description") or ""), max_chars=140)
            owner_hint = str(item.get("owner_hint") or item.get("owner") or "").strip()
            if surface:
                normalized.append({"surface": surface, "purpose": purpose, "owner_hint": owner_hint})
        elif isinstance(item, str) and item.strip():
            normalized.append({"surface": item.strip(), "purpose": "", "owner_hint": ""})
    return normalized


def _derive_api_contracts(requirements_json: dict[str, Any], profile_type: str) -> list[dict[str, Any]]:
    routes = requirements_json.get("routes_or_pages", [])
    normalized = _normalize_api_contracts(routes)
    if normalized:
        return normalized
    if profile_type == "fastapi_service":
        return [{"path": "/health", "methods": ["GET"], "purpose": "Health check endpoint"}]
    return [{"path": "/", "methods": ["GET"], "purpose": "Primary application route"}]


def _derive_data_entities(requirements_json: dict[str, Any]) -> list[dict[str, str]]:
    entities = _normalize_data_entities(requirements_json.get("data_model", []))
    return entities


def _derive_ui_surfaces(
    requirements_json: dict[str, Any],
    file_tree: list[str],
    profile_type: str,
) -> list[dict[str, str]]:
    derived = _normalize_ui_surfaces(requirements_json.get("routes_or_pages", []))
    if derived:
        return derived

    surfaces: list[dict[str, str]] = []
    if profile_type == "nextjs_webapp":
        for path in file_tree:
            if path.endswith(("page.tsx", "page.jsx")):
                surfaces.append({
                    "surface": path.replace("app/", "").replace("/page.tsx", "").replace("/page.jsx", "") or "home",
                    "purpose": "App route surface",
                    "owner_hint": "",
                })
    return surfaces[:10]


def _provider_responsibilities(provider: str, profile_type: str) -> list[str]:
    common = {
        "openai": [
            "Own the primary user-facing flows and top-level composition.",
            "Keep shared runtime/config files coherent and production-shaped.",
        ],
        "deepseek": [
            "Own core business logic, data flow, and edge-case handling.",
            "Bias toward correctness in state, API logic, and invariants.",
        ],
        "zhipu": [
            "Own validation-heavy flows, empty/error/loading states, and UX completeness.",
            "Bias toward consistent forms, schemas, and detail interactions.",
        ],
        "ollama": [
            "Own tests, fixtures, utility glue, and local-run safety nets.",
            "Bias toward pragmatic verification and support files.",
        ],
    }
    profile_specific = {
        "nextjs_webapp": {
            "openai": ["Shape the App Router surface, layouts, and visual polish."],
            "deepseek": ["Shape stores, hooks, derived filters, and server/client data boundaries."],
            "zhipu": ["Shape form handling, detail panels, and resilient UI states."],
            "ollama": ["Shape tests, fixtures, and helper utilities."],
        },
        "fastapi_service": {
            "openai": ["Shape route layer, docs-facing responses, and startup composition."],
            "deepseek": ["Shape services, repositories, and concurrency-sensitive logic."],
            "zhipu": ["Shape schemas, validation, auth/security middleware, and error envelopes."],
            "ollama": ["Shape tests, fixtures, and smoke scripts."],
        },
    }
    return common.get(provider, []) + profile_specific.get(profile_type, {}).get(provider, [])


def _provider_review_focus(provider: str, profile_type: str) -> list[str]:
    focus = {
        "openai": ["UI/API contract coherence", "missing integration glue", "broken primary flow"],
        "deepseek": ["logic correctness", "edge cases", "state consistency"],
        "zhipu": ["validation gaps", "empty/error states", "form behavior"],
        "ollama": ["testability", "local startup reliability", "missing config or fixtures"],
    }
    if profile_type == "fastapi_service":
        focus["openai"] = ["route/schema alignment", "response consistency", "main entry composition"]
    return focus.get(provider, ["interface mismatch"])


def _score_file_for_provider(path: str, provider: str, profile_type: str) -> int:
    path_lower = path.lower()
    score = 0

    if provider == "openai":
        if path_lower in {"package.json", "requirements.txt", "main.py", "app/layout.tsx", "app/page.tsx"}:
            score += 120
        if "/components/" in path_lower or path_lower.endswith((".css", ".scss")):
            score += 80
        if "layout" in path_lower or "page." in path_lower:
            score += 60

    if provider == "deepseek":
        if any(token in path_lower for token in ("/api/", "/lib/", "/store", "/hooks", "/services", "/repository", "/db", "/data")):
            score += 120
        if any(token in path_lower for token in ("logic", "filter", "search", "balance", "transfer", "compute")):
            score += 80

    if provider == "zhipu":
        if any(token in path_lower for token in ("form", "schema", "validation", "detail", "modal", "loading", "empty", "error")):
            score += 120
        if any(token in path_lower for token in ("auth", "security")):
            score += 80

    if provider == "ollama":
        if any(token in path_lower for token in ("test", "spec", "fixture", "seed", "script")):
            score += 120
        if path_lower.endswith((".md", ".sh")):
            score += 60

    if profile_type == "fastapi_service":
        if provider == "deepseek" and path_lower.endswith(".py"):
            score += 30
        if provider == "zhipu" and any(token in path_lower for token in ("schema", "security", "auth", "validator")):
            score += 30
    if profile_type == "nextjs_webapp":
        if provider == "openai" and path_lower.endswith((".tsx", ".css")):
            score += 25
        if provider == "deepseek" and path_lower.endswith((".ts", ".tsx")):
            score += 20

    return score


def _build_peer_review_pairs(planned_builders: list[str]) -> list[dict[str, Any]]:
    if len(planned_builders) < 2:
        return []
    pairs: list[dict[str, Any]] = []
    for index, reviewer in enumerate(planned_builders):
        target = planned_builders[(index + 1) % len(planned_builders)]
        pairs.append({"reviewer": reviewer, "target": target})
    return pairs


def build_deterministic_plan(
    *,
    profile_type: str,
    base_blueprint: dict[str, Any],
    requirements_json: dict[str, Any] | None,
    planned_builders: list[str],
) -> dict[str, Any]:
    file_tree = _normalize_file_tree(base_blueprint.get("file_tree")) or _default_file_tree(profile_type)
    requirements_json = requirements_json or {}
    provider_modules: dict[str, dict[str, Any]] = {}

    for provider in planned_builders:
        provider_modules[provider] = {
            "module_name": f"{provider.title()} module",
            "responsibilities": _provider_responsibilities(provider, profile_type),
            "owned_files": [],
            "review_focus": _provider_review_focus(provider, profile_type),
        }

    for path in file_tree:
        ranked = sorted(
            planned_builders,
            key=lambda provider: (_score_file_for_provider(path, provider, profile_type), provider == "openai"),
            reverse=True,
        )
        owner = ranked[0] if ranked else "openai"
        provider_modules.setdefault(owner, {
            "module_name": f"{owner.title()} module",
            "responsibilities": _provider_responsibilities(owner, profile_type),
            "owned_files": [],
            "review_focus": _provider_review_focus(owner, profile_type),
        })
        provider_modules[owner]["owned_files"].append(path)

    return {
        "summary": "Deterministic multi-model module plan.",
        "council_summary": ["Deterministic blueprint generated from confirmed requirements and file ownership heuristics."],
        "shared_contracts": [
            "Preserve agreed file ownership; avoid overwriting another model's owned files.",
            "Keep top-level dependencies and runtime commands consistent with the master blueprint.",
            "Honor shared data contracts across UI, API, and validation layers.",
        ],
        "integration_notes": [
            "Module owners may emit support files outside their scope, but synthesis prefers the declared owner version for owned files.",
            "If an owned file is missing, synthesis falls back to the best available contributor version.",
        ],
        "api_contracts": _derive_api_contracts(requirements_json, profile_type),
        "data_entities": _derive_data_entities(requirements_json),
        "ui_surfaces": _derive_ui_surfaces(requirements_json, file_tree, profile_type),
        "provider_modules": provider_modules,
        "peer_review_pairs": _build_peer_review_pairs(planned_builders),
        "file_tree": file_tree,
    }


async def request_provider_proposal(
    *,
    provider: str,
    builder: Any,
    profile_type: str,
    requirements_json: dict[str, Any],
    base_blueprint: dict[str, Any],
    deterministic_module: dict[str, Any],
) -> dict[str, Any]:
    try:
        prompt = _PROPOSAL_PROMPT.format(
            profile_type=profile_type,
            requirements_json=json.dumps(requirements_json, indent=2),
            base_blueprint_json=json.dumps(base_blueprint, indent=2),
            provider_focus_json=json.dumps(deterministic_module, indent=2),
            output_schema_json=_PROPOSAL_OUTPUT_SCHEMA_JSON,
        )
        result = await _provider_json_request(
            provider=provider,
            builder=builder,
            system_prompt=_PROPOSAL_SYSTEM_PROMPT,
            prompt=prompt,
        )
        if result:
            return result
    except Exception as exc:
        logger.warning("Architecture proposal failed for %s: %s", provider, exc)
    return {
        "summary": f"{provider} did not return a structured blueprint proposal.",
        "critical_files": deterministic_module.get("owned_files", [])[:6],
        "file_tree_delta": deterministic_module.get("owned_files", [])[:6],
        "api_contracts": [],
        "data_entities": [],
        "ui_surfaces": [],
        "module_boundaries": [],
        "integration_risks": [f"{provider} proposal unavailable"],
        "peer_review_focus": deterministic_module.get("review_focus", []),
    }


async def synthesize_master_blueprint(
    *,
    claude_client: Any | None,
    claude_model: str | None,
    profile_type: str,
    requirements_json: dict[str, Any],
    base_blueprint: dict[str, Any],
    deterministic_plan: dict[str, Any],
    council_proposals: list[dict[str, Any]],
) -> dict[str, Any]:
    if not claude_client or not claude_model:
        fallback = dict(deterministic_plan)
        fallback["summary"] = "Deterministic blueprint used because Claude synthesis is unavailable."
        fallback["council_summary"] = [
            _truncate_text(proposal.get("summary", ""), max_chars=180)
            for proposal in council_proposals
        ]
        return fallback

    try:
        prompt = _SYNTHESIS_PROMPT.format(
            profile_type=profile_type,
            requirements_json=json.dumps(requirements_json, indent=2),
            base_blueprint_json=json.dumps(base_blueprint, indent=2),
            deterministic_plan_json=json.dumps(deterministic_plan, indent=2),
            council_proposals_json=json.dumps(council_proposals, indent=2),
            output_schema_json=_SYNTHESIS_OUTPUT_SCHEMA_JSON,
        )
        response = await asyncio.wait_for(
            claude_client.messages.create(
                model=claude_model,
                max_tokens=4096,
                temperature=0.1,
                system=_SYNTHESIS_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=_SYNTHESIS_TIMEOUT_SECONDS,
        )
        content = "\n".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        )
        parsed = _parse_json_response(content)
        if parsed:
            return merge_master_blueprint(deterministic_plan, parsed)
    except Exception as exc:
        logger.warning("Claude synthesis failed; falling back to deterministic plan: %s", exc)

    fallback = dict(deterministic_plan)
    fallback["summary"] = "Deterministic blueprint used after synthesis fallback."
    return fallback


def merge_master_blueprint(
    deterministic_plan: dict[str, Any],
    synthesized_plan: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(deterministic_plan)
    merged["summary"] = synthesized_plan.get("summary") or deterministic_plan.get("summary")
    merged["council_summary"] = synthesized_plan.get("council_summary") or deterministic_plan.get("council_summary", [])
    merged["shared_contracts"] = synthesized_plan.get("shared_contracts") or deterministic_plan.get("shared_contracts", [])
    merged["integration_notes"] = synthesized_plan.get("integration_notes") or deterministic_plan.get("integration_notes", [])
    merged["api_contracts"] = _normalize_api_contracts(synthesized_plan.get("api_contracts")) or deterministic_plan.get("api_contracts", [])
    merged["data_entities"] = _normalize_data_entities(synthesized_plan.get("data_entities")) or deterministic_plan.get("data_entities", [])
    merged["ui_surfaces"] = _normalize_ui_surfaces(synthesized_plan.get("ui_surfaces")) or deterministic_plan.get("ui_surfaces", [])
    merged["provider_modules"] = {}

    deterministic_modules = deterministic_plan.get("provider_modules", {})
    synthesized_modules = synthesized_plan.get("provider_modules", {})

    for provider, deterministic_module in deterministic_modules.items():
        proposed = synthesized_modules.get(provider, {}) if isinstance(synthesized_modules, dict) else {}
        owned_files = proposed.get("owned_files")
        if not isinstance(owned_files, list) or not owned_files:
            owned_files = deterministic_module.get("owned_files", [])
        else:
            allowed_files = set(deterministic_plan.get("file_tree", []))
            owned_files = [path for path in owned_files if path in allowed_files] or deterministic_module.get("owned_files", [])

        merged["provider_modules"][provider] = {
            "module_name": proposed.get("module_name") or deterministic_module.get("module_name"),
            "responsibilities": proposed.get("responsibilities") or deterministic_module.get("responsibilities", []),
            "owned_files": owned_files,
            "review_focus": proposed.get("review_focus") or deterministic_module.get("review_focus", []),
        }

    merged["peer_review_pairs"] = deterministic_plan.get("peer_review_pairs", [])
    merged["file_tree"] = deterministic_plan.get("file_tree", [])
    return merged


def build_provider_requirements(
    *,
    base_requirements: dict[str, Any],
    master_blueprint: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    provider_module = master_blueprint.get("provider_modules", {}).get(provider, {})
    scoped = dict(base_requirements)
    scoped["assembly_protocol"] = {
        "protocol": "assembly_v1",
        "module_owner": provider,
        "module_name": provider_module.get("module_name"),
        "responsibilities": provider_module.get("responsibilities", []),
        "owned_files": provider_module.get("owned_files", []),
        "shared_contracts": master_blueprint.get("shared_contracts", []),
        "integration_notes": master_blueprint.get("integration_notes", []),
        "review_focus": provider_module.get("review_focus", []),
        "peer_review_pairs": [
            pair for pair in master_blueprint.get("peer_review_pairs", [])
            if pair.get("reviewer") == provider or pair.get("target") == provider
        ],
    }
    return scoped


def merge_synthesized_files(
    *,
    master_blueprint: dict[str, Any],
    candidate_files: dict[str, dict[str, str]],
    preferred_order: list[str],
) -> dict[str, Any]:
    provider_modules = master_blueprint.get("provider_modules", {})
    owner_for_path: dict[str, str] = {}
    for provider, module in provider_modules.items():
        for path in module.get("owned_files", []):
            owner_for_path[path] = provider

    all_paths = sorted({path for files in candidate_files.values() for path in files.keys()})
    merged_files: dict[str, str] = {}
    provenance: dict[str, str] = {}

    for path in all_paths:
        owner = owner_for_path.get(path)
        if owner and path in candidate_files.get(owner, {}):
            merged_files[path] = candidate_files[owner][path]
            provenance[path] = owner
            continue

        for provider in preferred_order:
            if path in candidate_files.get(provider, {}):
                merged_files[path] = candidate_files[provider][path]
                provenance[path] = provider
                break

    contributions: dict[str, int] = {}
    for provider in provenance.values():
        contributions[provider] = contributions.get(provider, 0) + 1

    return {
        "files": merged_files,
        "provenance": provenance,
        "contributions": contributions,
        "summary": "Synthesized baseline assembled from module ownership map.",
    }


async def request_peer_review(
    *,
    reviewer: str,
    reviewer_builder: Any,
    target: str,
    master_blueprint: dict[str, Any],
    target_scope: dict[str, Any],
    target_files: dict[str, str],
) -> dict[str, Any]:
    try:
        prompt = _REVIEW_PROMPT.format(
            reviewer=reviewer,
            target=target,
            master_blueprint_json=json.dumps(master_blueprint, indent=2),
            module_scope_json=json.dumps(target_scope, indent=2),
            target_files=_format_review_files(target_files),
            output_schema_json=_REVIEW_OUTPUT_SCHEMA_JSON,
        )
        result = await _provider_json_request(
            provider=reviewer,
            builder=reviewer_builder,
            system_prompt=_REVIEW_SYSTEM_PROMPT,
            prompt=prompt,
        )
        if result:
            return result
    except Exception as exc:
        logger.warning("Peer review failed for %s -> %s: %s", reviewer, target, exc)
    return {
        "verdict": "concerns",
        "summary": f"{reviewer} review unavailable",
        "critical_issues": [f"{reviewer} review failed"],
        "interface_gaps": [],
        "suggested_followups": [],
    }


def _format_review_files(files: dict[str, str], max_files: int = 6, max_chars: int = 1200) -> str:
    if not files:
        return "(no files)"
    sections: list[str] = []
    for index, (name, content) in enumerate(sorted(files.items())):
        if index >= max_files:
            break
        snippet = content[:max_chars]
        if len(content) > max_chars:
            snippet += "\n... [truncated]"
        sections.append(f"### {name}\n```\n{snippet}\n```")
    omitted = len(files) - min(len(files), max_files)
    if omitted > 0:
        sections.append(f"... {omitted} additional files omitted")
    return "\n\n".join(sections)


async def _provider_json_request(
    *,
    provider: str,
    builder: Any,
    system_prompt: str,
    prompt: str,
) -> dict[str, Any]:
    if provider in {"openai", "zhipu"}:
        response = await asyncio.wait_for(
            builder.client.chat.completions.create(
                model=builder.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            ),
            timeout=_PROVIDER_JSON_TIMEOUT_SECONDS,
        )
        return _parse_json_response(response.choices[0].message.content or "")

    if provider == "deepseek":
        response = await asyncio.wait_for(
            builder.client.chat.completions.create(
                model=builder.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
            ),
            timeout=_PROVIDER_JSON_TIMEOUT_SECONDS,
        )
        return _parse_json_response(response.choices[0].message.content or "")

    if provider == "ollama":
        async with httpx.AsyncClient(timeout=builder.timeout) as client:
            response = await client.post(
                f"{builder.base_url}/api/chat",
                json={
                    "model": builder.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "format": "json",
                },
            )
            response.raise_for_status()
            body = response.json()
            content = body.get("message", {}).get("content", "{}")
            return _parse_json_response(content)

    raise ValueError(f"Unsupported provider for JSON request: {provider}")
