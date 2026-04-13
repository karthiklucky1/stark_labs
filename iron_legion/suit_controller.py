"""
Stark Labs — Iron Legion Suit Controller (J.A.R.V.I.S.)
─────────────────────────────────────────────────────────
Architecture:
  1. Planner   — GPT-4o decides which modules are needed and in what order
  2. DAG Build — modules with no dependency on each other run in PARALLEL
  3. Executor  — topological execution via asyncio.gather for parallel nodes
  4. Disassembly — modules shut down after pipeline completes

DAG dependency rules (hardcoded for invoice pipeline):
  PDF Reader  → runs first if input is a file path
  Translation → runs before Invoice Parser / Extraction (needs English text)
  Extraction  → independent from Invoice Parser (can run in parallel after Translation)
  Invoice Parser → must precede Payment
  Payment     → terminal node
"""
import os
import sys
import asyncio
import time
from pathlib import Path

from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).parent.parent))
from stark_logger import log
from stark_modules import AVAILABLE_MODULES

client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# ─────────────────────────────────────────────
# DAG dependency map
# key = module name, value = list of modules that must complete BEFORE it
# ─────────────────────────────────────────────
MODULE_DEPS: dict[str, list[str]] = {
    "PDF Reader":      [],
    "Translation":     ["PDF Reader"],
    "Extraction":      ["Translation", "PDF Reader"],
    "Invoice Parser":  ["Translation"],
    "JSON Formatting": [],
    "Payment":         ["Invoice Parser"],
}


def _resolve_pipeline_deps(requested: list[str]) -> list[list[str]]:
    """
    Given an ordered list of module names, build execution waves
    using topological sort. Modules in the same wave have no
    dependency on each other and can run in parallel.

    Returns: list of waves, each wave is a list of module names.
    """
    # Only keep deps that are also in the requested pipeline
    active = set(requested)
    dep_map: dict[str, set[str]] = {
        m: {d for d in MODULE_DEPS.get(m, []) if d in active}
        for m in requested
    }

    waves: list[list[str]] = []
    completed: set[str] = set()

    while len(completed) < len(requested):
        # Find all modules whose deps are all completed
        ready = [
            m for m in requested
            if m not in completed and dep_map[m].issubset(completed)
        ]
        if not ready:
            # Circular dependency or unknown dep — fall back to sequential
            remaining = [m for m in requested if m not in completed]
            waves.append(remaining)
            break
        waves.append(ready)
        completed.update(ready)

    return waves


async def plan_pipeline(user_request: str) -> list[str]:
    """J.A.R.V.I.S. decides which modules to assemble and in what logical order."""
    module_list = list(AVAILABLE_MODULES.keys())
    system_prompt = (
        "You are J.A.R.V.I.S. — the Stark Labs Suit Controller.\n"
        f"Available modules: {module_list}\n\n"
        "Module purposes:\n"
        "  PDF Reader     — extract text from a PDF file path\n"
        "  Translation    — translate non-English text to English\n"
        "  Extraction     — extract named entities (people, amounts, dates)\n"
        "  Invoice Parser — parse English invoice text into structured JSON\n"
        "  JSON Formatting— coerce any text into a generic JSON object\n"
        "  Payment        — execute payment from a structured invoice JSON\n\n"
        "Based on the user's request, output a comma-separated list of EXACT module "
        "names in logical order. Only include modules that are actually needed.\n"
        "Output ONLY the comma-separated list. Nothing else."
    )
    resp = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_request},
        ],
        temperature=0,
    )
    raw = resp.choices[0].message.content.strip()
    modules = [m.strip() for m in raw.split(",")]
    valid = [m for m in modules if m in AVAILABLE_MODULES]
    log("pipeline_planned", modules=valid)
    return valid


async def execute_iron_legion(user_request: str, data_payload: str):
    print("\n" + "=" * 60)
    print("  STARK LABS — IRON LEGION: SUIT ASSEMBLY")
    print("=" * 60)

    print(f"\n[J.A.R.V.I.S.] Analyzing: \"{user_request[:80]}\"")
    pipeline = await plan_pipeline(user_request)
    print(f"[J.A.R.V.I.S.] Modules required: {pipeline}")

    # Build execution waves from DAG
    waves = _resolve_pipeline_deps(pipeline)
    wave_count = len(waves)
    parallel_waves = sum(1 for w in waves if len(w) > 1)
    print(f"[J.A.R.V.I.S.] Execution plan: {wave_count} wave(s), {parallel_waves} parallel")

    # Track outputs per module so parallel branches can merge
    outputs: dict[str, str] = {}
    current_input = data_payload
    total_start = time.time()

    for wave_idx, wave in enumerate(waves):
        if len(wave) > 1:
            print(f"\n  [WAVE {wave_idx + 1}] PARALLEL — {wave}")
        else:
            print(f"\n  [WAVE {wave_idx + 1}] {wave[0]}")

        async def run_module(name: str, inp: str) -> tuple[str, str]:
            t0 = time.time()
            func = AVAILABLE_MODULES[name]
            result = await func(inp)
            elapsed = time.time() - t0
            print(f"     [{name}] done in {elapsed:.2f}s → {str(result)[:120]}")
            return name, result

        # Parallel execution within the wave
        wave_results = await asyncio.gather(
            *[run_module(name, current_input) for name in wave],
            return_exceptions=True,
        )

        for name, result in wave_results:
            if isinstance(result, BaseException):
                print(f"  !! [{name}] FAILED: {result}")
                log("module_error", module=name, error=str(result))
            else:
                outputs[name] = result

        # The last module in the wave that succeeded feeds the next wave
        last_success = next(
            (outputs[name] for name in reversed(wave) if name in outputs),
            current_input,
        )
        current_input = last_success

    elapsed_total = time.time() - total_start
    print(f"\n[J.A.R.V.I.S.] Pipeline complete in {elapsed_total:.2f}s")
    print("[J.A.R.V.I.S.] Modules disassembling...\n")
    log("pipeline_complete", elapsed_s=round(elapsed_total, 2), modules=pipeline)

    print("─" * 60)
    print("  FINAL OUTPUT")
    print("─" * 60)
    print(current_input)
    return current_input


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")

    print("=== STARK LABS: IRON LEGION DEMO ===")

    # Example 1: Plain text invoice-style input
    raw_text = (
        "Invoice #1042 from Stark Industries to Pepper Potts.\n"
        "Date: 2026-04-08\n"
        "Line items:\n"
        "  - Arc Reactor Maintenance x1  $4,500.00\n"
        "  - Repulsor Array Upgrade  x2  $1,200.00 each\n"
        "Subtotal: $6,900.00  Tax (8%): $552.00  Total: $7,452.00  Currency: USD"
    )
    instruction = "Parse this invoice and simulate a payment."

    print(f"\nInput: {raw_text[:100]}...")
    print(f"Request: {instruction}\n")

    asyncio.run(execute_iron_legion(instruction, raw_text))
