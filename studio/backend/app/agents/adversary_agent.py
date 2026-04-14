from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import List, Dict, Any

import httpx
from openai import AsyncOpenAI

from app.settings import settings

logger = logging.getLogger(__name__)

# LLM call timeout for each individual adversary request
_LLM_TIMEOUT = 30.0
_ATTACK_CONNECT_TIMEOUT_S = 10.0
_ATTACK_READ_TIMEOUT_S = 30.0
_ATTACK_WRITE_TIMEOUT_S = 15.0
_ATTACK_POOL_TIMEOUT_S = 15.0
_ATTACK_RETRY_DELAY_S = 1.5


class AdversaryAgent:
    """
    Mark VII Autonomous Adversary Agent.

    Uses AsyncOpenAI so calls don't block the event loop.
    Performs reconnaissance on candidate source files, synthesizes 3 targeted
    attack waves, and executes them against the live sandbox.
    """

    def __init__(self, model: str | None = None):
        resolved_model = model or settings.openai_adversary_model or settings.openai_builder_model
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            timeout=_LLM_TIMEOUT,
        )
        self.model = resolved_model
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
        timeout = httpx.Timeout(
            connect=_ATTACK_CONNECT_TIMEOUT_S,
            read=_ATTACK_READ_TIMEOUT_S,
            write=_ATTACK_WRITE_TIMEOUT_S,
            pool=_ATTACK_POOL_TIMEOUT_S,
        )
        async with httpx.AsyncClient(timeout=timeout) as http:
            await _warm_service_root(http, base_url)
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
            return _wave_error(
                wave,
                f"Probe synthesis failed: {_describe_exception(e)}",
                outcome="probe_synthesis_failed",
            )

        try:
            resp, latency = await _execute_attack_request(http, base_url, spec)
        except Exception as e:
            return _wave_error(
                wave,
                f"Request failed: {_describe_exception(e)}",
                outcome="execution_failed",
            )

        try:
            judge_prompt = (
                "Decide whether this attack produced evidence of a REAL security breach.\n"
                "Only return breach_confirmed=true when the response proves unauthorized access, "
                "data exposure, privilege escalation, logic bypass, or harmful action execution.\n"
                "A generic framework page, HTTP 200 alone, validation failure, timeout, or app shell "
                "response is NOT evidence of a breach.\n"
                f"ATTACK: {wave.get('name')}\n"
                f"STATUS: {resp.status_code}\nBODY: {resp.text[:400]}\n\n"
                'Return JSON: {"breach_confirmed": false, "details": "string", "confidence": "high|medium|low"}'
            )
            judge_res = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": judge_prompt}],
                response_format={"type": "json_object"},
            )
            judgment = json.loads(judge_res.choices[0].message.content)
            details = _extract_judgment_details(judgment)
            breach_confirmed = _extract_breach_confirmation(judgment, details)
            return {
                "name":     wave.get("name", "unknown"),
                "passed":   not breach_confirmed,
                "critical": breach_confirmed,
                "details":  [details, f"HTTP {resp.status_code}", f"{latency:.2f}s"],
                "metrics":  {
                    "status": resp.status_code,
                    "latency": latency,
                    "outcome": "breach" if breach_confirmed else "no_breach",
                    "judge_confidence": judgment.get("confidence"),
                },
            }
        except Exception as e:
            judge_error = _describe_exception(e)
            details = [
                "Judge unavailable; no confirmed security bypass.",
                f"Judge error: {judge_error}",
                f"HTTP {resp.status_code}",
                f"{latency:.2f}s",
            ]
            return {
                "name": wave.get("name", "unknown"),
                "passed": False,
                "critical": False,
                "details": details,
                "metrics": {
                    "status": resp.status_code,
                    "latency": latency,
                    "judge_error": judge_error,
                    "outcome": "judge_unavailable",
                },
            }


# ── helpers ──────────────────────────────────────────────────────────

def _summarise_files(files_json: Dict[str, str]) -> str:
    """Truncate each file to 1500 chars and join into a single context block."""
    parts = []
    for name, content in files_json.items():
        if any(name.endswith(ext) for ext in (".py", ".js", ".ts", ".tsx")):
            parts.append(f"FILE: {name}\n{content[:1500]}")
    return "\n\n".join(parts) if parts else "(no source files)"


def _wave_error(wave: Dict[str, Any], msg: str, *, outcome: str) -> Dict[str, Any]:
    return {
        "name":     wave.get("name", "unknown"),
        "passed":   False,
        "critical": False,
        "details":  [msg],
        "metrics":  {"error": msg, "outcome": outcome},
    }


def _describe_exception(exc: Exception) -> str:
    message = str(exc).strip()
    if message:
        return f"{exc.__class__.__name__}: {message}"
    return exc.__class__.__name__


def _extract_judgment_details(judgment: Dict[str, Any]) -> str:
    for key in ("details", "reasoning", "evidence", "summary"):
        value = judgment.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "No detailed judgment returned."


def _extract_breach_confirmation(judgment: Dict[str, Any], details: str) -> bool:
    explicit = judgment.get("breach_confirmed")
    if isinstance(explicit, bool):
        return explicit

    explicit = judgment.get("security_breached")
    if isinstance(explicit, bool):
        return explicit

    legacy = judgment.get("passed_security")
    if isinstance(legacy, bool):
        lowered = details.lower()
        if any(
            marker in lowered
            for marker in (
                "does not show",
                "not evidence",
                "no confirmed",
                "normal next.js page",
                "normal page load",
                "generic html",
                "app shell",
            )
        ):
            return False
        return legacy

    return False


async def _warm_service_root(http: httpx.AsyncClient, base_url: str) -> None:
    """Prime dev servers like Next.js before adversarial traffic starts."""
    try:
        await http.get(f"{base_url}/", headers={"x-stark-warmup": "1"})
    except Exception:
        pass


async def _execute_attack_request(
    http: httpx.AsyncClient,
    base_url: str,
    spec: Dict[str, Any],
) -> tuple[httpx.Response, float]:
    method = str(spec.get("method") or "GET").upper()
    path = str(spec.get("path") or "/")
    headers = spec.get("headers") or {}
    payload = spec.get("payload") or None
    last_error: Exception | None = None

    for attempt in range(2):
        try:
            t0 = time.monotonic()
            response = await http.request(
                method=method,
                url=f"{base_url}{path}",
                json=payload,
                headers=headers,
            )
            return response, time.monotonic() - t0
        except (httpx.ReadTimeout, httpx.ConnectError) as exc:
            last_error = exc
            if attempt == 0:
                await _warm_service_root(http, base_url)
                await asyncio.sleep(_ATTACK_RETRY_DELAY_S)
                continue
            raise

    if last_error is not None:
        raise last_error
    raise RuntimeError("Attack request failed without a captured exception")
