import os
import json
import logging
import time
from typing import List, Dict, Any
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# LLM call timeout for each individual adversary request
_LLM_TIMEOUT = 30.0


class AdversaryAgent:
    """
    Mark VII Autonomous Adversary Agent.

    Uses AsyncOpenAI so calls don't block the event loop.
    Performs reconnaissance on candidate source files, synthesizes 3 targeted
    attack waves, and executes them against the live sandbox.
    """

    def __init__(self, model: str = "gpt-4o"):
        self.client = AsyncOpenAI(
            api_key=os.environ.get("OPENAI_API_KEY"),
            timeout=_LLM_TIMEOUT,
        )
        self.model = model
        self.persona = (
            "You are the Stark Labs Adversary Agent (Mark VII). "
            "Your goal is intelligent red-teaming of provided source code. "
            "Focus on: logic flaws, auth bypasses, injection vectors, "
            "and patterns inspired by historical CVEs."
        )

    # ------------------------------------------------------------------
    # recon_surface now accepts files_json dict instead of a disk path
    # ------------------------------------------------------------------
    async def recon_surface(self, files_json: Dict[str, str]) -> Dict[str, Any]:
        """Analyse candidate source files and map the attack surface."""
        code_summary = _summarise_files(files_json)

        prompt = (
            "Analyze this codebase and map the ATTACK SURFACE. "
            "Identify the 3 most critical logical entry points where high-value data is processed.\n\n"
            f"CODE_DUMP:\n{code_summary}\n\n"
            "Return JSON:\n"
            '{"surface_map": [{"endpoint": "string", "logic_flow": "string", '
            '"risk_factor": "high|med|low", "reasoning": "string"}], '
            '"recommended_focus": "string"}'
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.persona},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    async def synthesize_attack_waves(self, surface_map: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate 3 targeted attack cases from the mapped surface."""
        prompt = (
            "Based on these entry points, synthesize exactly 3 UNCONVENTIONAL logical attack cases. "
            "Reference non-obvious CVE patterns where applicable.\n\n"
            f"SURFACE:\n{json.dumps(surface_map, indent=2)}\n\n"
            'Return JSON: {"attack_waves": [{'
            '"name": "Snake_Case", "category": "string", '
            '"vulnerability_logic": "string", '
            '"payload_generator_prompt": "string"}]}'
        )

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self.persona},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        if isinstance(result, dict):
            for key in ("attack_waves", "attacks", "waves"):
                if key in result and isinstance(result[key], list):
                    return result[key]
        return result if isinstance(result, list) else []

    async def run_attack_waves(self, base_url: str, waves: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute all attack waves in parallel against the live sandbox."""
        import asyncio
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as http:
            tasks = [self._run_single_wave(http, base_url, wave) for wave in waves]
            return await asyncio.gather(*tasks)

    async def _run_single_wave(self, http: Any, base_url: str, wave: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one attack wave: synthesize → fire → judge."""
        logger.info("Executing wave: %s", wave.get("name", "?"))

        probe_prompt = (
            "Synthesize a SPECIFIC HTTP request to execute this attack wave.\n"
            f"WAVE: {json.dumps(wave)}\nBASE_URL: {base_url}\n\n"
            'Return JSON: {"method": "POST|GET|PATCH|DELETE", '
            '"path": "/absolute/path", "payload": {}, "headers": {}}'
        )
        try:
            probe_res = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": probe_prompt}],
                response_format={"type": "json_object"},
            )
            spec = json.loads(probe_res.choices[0].message.content)
        except Exception as e:
            return _wave_error(wave, f"Probe synthesis failed: {e}")

        try:
            t0 = time.monotonic()
            resp = await http.request(
                method=spec.get("method", "GET"),
                url=f"{base_url}{spec.get('path', '/')}",
                json=spec.get("payload") or None,
                headers=spec.get("headers") or {},
            )
            latency = time.monotonic() - t0

            judge_prompt = (
                "Judge if this attack SUCCEEDED in bypassing security.\n"
                f"ATTACK: {wave.get('name')}\n"
                f"STATUS: {resp.status_code}\nBODY: {resp.text[:400]}\n\n"
                'Return JSON: {"passed_security": true, "details": "string"}'
            )
            judge_res = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": judge_prompt}],
                response_format={"type": "json_object"},
            )
            judgment = json.loads(judge_res.choices[0].message.content)
            return {
                "name":     wave.get("name", "unknown"),
                "passed":   bool(judgment.get("passed_security", True)),
                "critical": not bool(judgment.get("passed_security", True)),
                "details":  [judgment.get("details", ""), f"HTTP {resp.status_code}", f"{latency:.2f}s"],
                "metrics":  {"status": resp.status_code, "latency": latency},
            }
        except Exception as e:
            return _wave_error(wave, f"Request/judge failed: {e}")


# ── helpers ──────────────────────────────────────────────────────────

def _summarise_files(files_json: Dict[str, str]) -> str:
    """Truncate each file to 1500 chars and join into a single context block."""
    parts = []
    for name, content in files_json.items():
        if any(name.endswith(ext) for ext in (".py", ".js", ".ts", ".tsx")):
            parts.append(f"FILE: {name}\n{content[:1500]}")
    return "\n\n".join(parts) if parts else "(no source files)"


def _wave_error(wave: Dict[str, Any], msg: str) -> Dict[str, Any]:
    return {
        "name":     wave.get("name", "unknown"),
        "passed":   False,
        "critical": True,
        "details":  [msg],
        "metrics":  {"error": msg},
    }
