from __future__ import annotations

import json

from .config import PATCH_MEMORY_FILE


def load_patch_memory() -> list[dict]:
    if PATCH_MEMORY_FILE.exists():
        with open(PATCH_MEMORY_FILE) as file:
            return json.load(file)
    return []


def save_patch_memory(memory: list[dict]) -> None:
    with open(PATCH_MEMORY_FILE, "w") as file:
        json.dump(memory, file, indent=2)


def render_patch_history(memory: list[dict], task_name: str | None = None) -> str:
    if task_name is not None:
        memory = [
            patch for patch in memory
            if patch.get("task_name") in (None, task_name)
        ]

    if not memory:
        return "None yet."

    lines: list[str] = []
    for patch in memory:
        result = "accepted" if patch.get("accepted") else "rejected"
        provider = patch.get("selected_provider")
        model = patch.get("selected_model")
        failure = patch.get("failure_type") or patch.get("rejection_reason") or "unknown"
        if provider and model:
            lines.append(
                f"- Mark {patch.get('mark', '?')}: {result} via {provider}/{model}; trigger={failure}"
            )
        else:
            lines.append(f"- Mark {patch.get('mark', '?')}: {result}; trigger={failure}")
    return "\n".join(lines)
