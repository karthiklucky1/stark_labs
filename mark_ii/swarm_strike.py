"""
Stark Labs — Adversary Swarm
Phase 1 upgrade:
  - returns structured JSON in --json mode
  - keeps human-readable output in default mode
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Optional, Union
import json
import sys
import time
from urllib.parse import quote

import httpx

from .schemas import PhaseResult, SwarmReport
from .task_spec import TaskSpec, load_task_spec

TIMEOUT = httpx.Timeout(10.0)


def emit(verbose: bool, message: str) -> None:
    if verbose:
        print(message)


def _context(task_spec: TaskSpec, key: str, default):
    return task_spec.context.get(key, default)


def _transfer_path(task_spec: TaskSpec) -> str:
    return str(_context(task_spec, "transfer_path", "/transfer"))


def _reset_path(task_spec: TaskSpec) -> str:
    return str(_context(task_spec, "reset_path", "/reset"))


def _balance_path(task_spec: TaskSpec, user_id: str) -> str:
    template = str(_context(task_spec, "balance_path_template", "/balance/{user_id}"))
    return template.format(user_id=user_id)


def _seed_user(task_spec: TaskSpec) -> str:
    return str(_context(task_spec, "seed_user_id", "user_1"))


async def phase_race_condition(
    client: httpx.AsyncClient,
    base_url: str,
    verbose: bool,
    task_spec: TaskSpec,
) -> PhaseResult:
    seed_user = _seed_user(task_spec)
    transfer_path = _transfer_path(task_spec)
    reset_path = _reset_path(task_spec)
    balance_path = _balance_path(task_spec, seed_user)
    attack_amount = float(_context(task_spec, "attack_transfer_amount", 10.0))
    max_successes = int(_context(task_spec, "max_expected_successes_under_race", 10))

    await client.post(f"{base_url}{reset_path}")
    emit(verbose, "\n[PHASE 1] Race Condition Attack — 100 concurrent $10 transfers")

    async def transfer() -> httpx.Response | Exception:
        try:
            return await client.post(
                f"{base_url}{transfer_path}",
                json={"user_id": seed_user, "amount": attack_amount},
                timeout=TIMEOUT,
            )
        except Exception as error:
            return error

    start = time.time()
    results = await asyncio.gather(*(transfer() for _ in range(100)))
    elapsed = time.time() - start

    successes = [response for response in results if isinstance(response, httpx.Response) and response.status_code == 200]
    errors = [response for response in results if isinstance(response, Exception)]

    balance_response = await client.get(f"{base_url}{balance_path}", timeout=TIMEOUT)
    balance = balance_response.json().get("balance", 0.0)

    details = [
        f"Successful transfers={len(successes)}",
        f"Errors={len(errors)}",
        f"Balance={balance}",
        f"Elapsed={elapsed:.2f}s",
    ]
    critical = len(successes) > max_successes or balance < 0
    if critical:
        details.append("Race condition confirmed")

    emit(verbose, f"  Successful transfers: {len(successes)} | Errors: {len(errors)} | Balance: ${balance:.2f} | {elapsed:.2f}s")
    if critical:
        emit(verbose, "  !! CRITICAL: Race condition armor failed")
    else:
        emit(verbose, "  ✓ Race condition armor held")

    return PhaseResult(
        phase_id=1,
        name="Race Condition",
        passed=not critical,
        critical=critical,
        details=details,
        metrics={
            "successful_transfers": len(successes),
            "errors": len(errors),
            "balance": balance,
            "elapsed_s": round(elapsed, 2),
        },
    )


INJECTION_PAYLOADS = [
    {"user_id": "' OR 1=1; DROP TABLE users; --", "amount": 10.0},
    {"user_id": "<script>alert(1)</script>", "amount": 10.0},
    {"user_id": "user_1\x00evil", "amount": 10.0},
    {"user_id": "A" * 10_000, "amount": 10.0},
    {"user_id": "user_1", "amount": "ten dollars"},
    {"user_id": None, "amount": 10.0},
    {"user_id": {"nested": "object"}, "amount": 10.0},
    {"user_id": "user_1", "amount": {"price": 10}},
]


async def phase_payload_injection(
    client: httpx.AsyncClient,
    base_url: str,
    verbose: bool,
    task_spec: TaskSpec,
) -> PhaseResult:
    emit(verbose, "\n[PHASE 2] Payload Injection Attack")
    critical = False
    accepted_statuses = 0
    details: list[str] = []
    transfer_path = _transfer_path(task_spec)

    for payload in INJECTION_PAYLOADS:
        try:
            response = await client.post(f"{base_url}{transfer_path}", json=payload, timeout=TIMEOUT)
            status = response.status_code
            details.append(f"payload={str(payload)[:60]} status={status}")
            if status == 500:
                critical = True
                emit(verbose, f"  !! CRITICAL: Server 500 on payload: {str(payload)[:60]}")
            else:
                if status == 200:
                    accepted_statuses += 1
                emit(verbose, f"  ✓ Payload handled with {status}: {str(payload)[:60]}")
        except Exception as error:
            critical = True
            details.append(f"payload={str(payload)[:60]} error={error}")
            emit(verbose, f"  !! CRITICAL: Server crashed on payload: {str(payload)[:60]}")

    return PhaseResult(
        phase_id=2,
        name="Payload Injection",
        passed=not critical,
        critical=critical,
        details=details,
        metrics={"payloads_tested": len(INJECTION_PAYLOADS), "accepted_statuses": accepted_statuses},
    )


BOUNDARY_CASES = [
    {"user_id": "user_1", "amount": -1000.0},
    {"user_id": "user_1", "amount": 0.0},
    {"user_id": "user_1", "amount": 1e308},
    {"user_id": "user_1", "amount": -0.0001},
    {"user_id": "ghost_user", "amount": 10.0},
]


async def phase_boundary_attack(
    client: httpx.AsyncClient,
    base_url: str,
    verbose: bool,
    task_spec: TaskSpec,
) -> PhaseResult:
    transfer_path = _transfer_path(task_spec)
    reset_path = _reset_path(task_spec)
    seed_user = _seed_user(task_spec)
    await client.post(f"{base_url}{reset_path}")
    emit(verbose, "\n[PHASE 3] Boundary Attack")
    critical = False
    details: list[str] = []

    for payload in BOUNDARY_CASES:
        amount = payload["amount"]
        try:
            request_payload = dict(payload)
            if request_payload["user_id"] == "user_1":
                request_payload["user_id"] = seed_user
            response = await client.post(f"{base_url}{transfer_path}", json=request_payload, timeout=TIMEOUT)
            status = response.status_code
            details.append(f"amount={amount} status={status}")
            if amount <= 0 and status == 200:
                critical = True
                emit(verbose, f"  !! CRITICAL: Server accepted invalid amount={amount} with 200 OK")
            elif status == 500:
                critical = True
                emit(verbose, f"  !! CRITICAL: Server 500 on boundary case amount={amount}")
            else:
                emit(verbose, f"  ✓ Boundary {amount} correctly returned {status}")
        except Exception as error:
            critical = True
            details.append(f"amount={amount} error={error}")
            emit(verbose, f"  !! CRITICAL: Server crashed on boundary case amount={amount}")

    return PhaseResult(
        phase_id=3,
        name="Boundary Attack",
        passed=not critical,
        critical=critical,
        details=details,
        metrics={"cases_tested": len(BOUNDARY_CASES)},
    )


async def phase_endpoint_flood(
    client: httpx.AsyncClient,
    base_url: str,
    verbose: bool,
    task_spec: TaskSpec,
) -> PhaseResult:
    emit(verbose, "\n[PHASE 4] Endpoint Flood — Concurrent resets vs transfers")
    seed_user = _seed_user(task_spec)
    transfer_path = _transfer_path(task_spec)
    reset_path = _reset_path(task_spec)
    balance_path = _balance_path(task_spec, seed_user)
    attack_amount = float(_context(task_spec, "attack_transfer_amount", 10.0))

    await client.post(f"{base_url}{reset_path}")
    for _ in range(9):
        await client.post(
            f"{base_url}{transfer_path}",
            json={"user_id": seed_user, "amount": attack_amount},
            timeout=TIMEOUT,
        )

    async def spam_reset() -> None:
        for _ in range(50):
            try:
                await client.post(f"{base_url}{reset_path}", timeout=TIMEOUT)
            except Exception:
                pass

    async def spam_transfer() -> list[httpx.Response]:
        responses: list[httpx.Response] = []
        for _ in range(50):
            try:
                response = await client.post(
                    f"{base_url}{transfer_path}",
                    json={"user_id": seed_user, "amount": attack_amount},
                    timeout=TIMEOUT,
                )
                responses.append(response)
            except Exception:
                pass
        return responses

    _, transfer_results = await asyncio.gather(spam_reset(), spam_transfer())
    successes = [response for response in transfer_results if response.status_code == 200]

    balance_response = await client.get(f"{base_url}{balance_path}", timeout=TIMEOUT)
    balance = balance_response.json().get("balance", 100.0)
    critical = balance < -50
    details = [
        f"successful_transfers_during_flood={len(successes)}",
        f"final_balance={balance}",
    ]
    if critical:
        details.append("Flood race corrupted account state")

    emit(verbose, f"  Transfers that succeeded during flood: {len(successes)} | Final balance: ${balance:.2f}")
    if critical:
        emit(verbose, "  !! CRITICAL: Flood attack corrupted account state")
    else:
        emit(verbose, "  ✓ Flood attack contained")

    return PhaseResult(
        phase_id=4,
        name="Endpoint Flood",
        passed=not critical,
        critical=critical,
        details=details,
        metrics={
            "successful_transfers_during_flood": len(successes),
            "final_balance": balance,
        },
    )


MALFORMED_JSON_PAYLOADS = [
    "{",
    "{\"user_id\": \"user_1\"",
    "{\"user_id\": \"user_1\", \"amount\": }",
    "not-json",
]


async def phase_malformed_json_attack(
    client: httpx.AsyncClient,
    base_url: str,
    verbose: bool,
    task_spec: TaskSpec,
) -> PhaseResult:
    emit(verbose, "\n[PHASE 5] Malformed JSON Attack")
    statuses: dict[str, int] = {}
    critical = False
    details: list[str] = []
    transfer_path = _transfer_path(task_spec)
    seed_user = _seed_user(task_spec)
    balance_path = _balance_path(task_spec, seed_user)

    for payload in MALFORMED_JSON_PAYLOADS:
        try:
            response = await client.post(
                f"{base_url}{transfer_path}",
                content=payload,
                headers={"content-type": "application/json"},
                timeout=TIMEOUT,
            )
            key = str(response.status_code)
            statuses[key] = statuses.get(key, 0) + 1
            details.append(f"payload={payload[:40]!r} status={response.status_code}")
            if response.status_code >= 500:
                critical = True
                emit(verbose, f"  !! CRITICAL: Server 500 on malformed payload {payload[:40]!r}")
            else:
                emit(verbose, f"  ✓ Malformed payload handled with {response.status_code}")
        except Exception as error:
            critical = True
            details.append(f"payload={payload[:40]!r} error={error}")
            emit(verbose, f"  !! CRITICAL: Server crashed on malformed payload {payload[:40]!r}")

    health_check = await client.get(f"{base_url}{balance_path}", timeout=TIMEOUT)
    if health_check.status_code >= 500:
        critical = True
        details.append(f"post_malformed_balance_status={health_check.status_code}")

    return PhaseResult(
        phase_id=5,
        name="Malformed JSON",
        passed=not critical,
        critical=critical,
        details=details,
        metrics={
            "payloads_tested": len(MALFORMED_JSON_PAYLOADS),
            "status_counts": statuses,
            "post_attack_balance_status": health_check.status_code,
        },
    )


PATH_PROBE_PAYLOADS = [
    "user_1",
    "ghost_user",
    "..%2Fetc%2Fpasswd",
    "%00evil",
    "<script>alert(1)</script>",
]


async def phase_path_probe(
    client: httpx.AsyncClient,
    base_url: str,
    verbose: bool,
    task_spec: TaskSpec,
) -> PhaseResult:
    emit(verbose, "\n[PHASE 6] Path Probe Attack")
    critical = False
    statuses: dict[str, int] = {}
    details: list[str] = []
    balance_template = str(_context(task_spec, "balance_path_template", "/balance/{user_id}"))

    for payload in PATH_PROBE_PAYLOADS:
        try:
            response = await client.get(
                f"{base_url}{balance_template.format(user_id=quote(payload, safe=''))}",
                timeout=TIMEOUT,
            )
            key = str(response.status_code)
            statuses[key] = statuses.get(key, 0) + 1
            details.append(f"user_id={payload[:40]!r} status={response.status_code}")
            if response.status_code >= 500:
                critical = True
                emit(verbose, f"  !! CRITICAL: Server 500 on path probe {payload[:40]!r}")
            else:
                emit(verbose, f"  ✓ Path probe handled with {response.status_code}")
        except Exception as error:
            critical = True
            details.append(f"user_id={payload[:40]!r} error={error}")
            emit(verbose, f"  !! CRITICAL: Server crashed on path probe {payload[:40]!r}")

    return PhaseResult(
        phase_id=6,
        name="Path Probe",
        passed=not critical,
        critical=critical,
        details=details,
        metrics={
            "payloads_tested": len(PATH_PROBE_PAYLOADS),
            "status_counts": statuses,
        },
    )


async def _run_phase_suite(
    client: httpx.AsyncClient,
    base_url: str,
    verbose: bool,
    task_spec: TaskSpec,
) -> list[PhaseResult]:
    if task_spec.attack_profile != "payment_api":
        raise RuntimeError(f"Unsupported attack profile: {task_spec.attack_profile}")
    return [
        await phase_race_condition(client, base_url, verbose, task_spec),
        await phase_payload_injection(client, base_url, verbose, task_spec),
        await phase_boundary_attack(client, base_url, verbose, task_spec),
        await phase_endpoint_flood(client, base_url, verbose, task_spec),
        await phase_malformed_json_attack(client, base_url, verbose, task_spec),
        await phase_path_probe(client, base_url, verbose, task_spec),
    ]


async def build_swarm_report(
    base_url: str,
    verbose: bool,
    client: Optional[httpx.AsyncClient] = None,
    task_spec: Optional[TaskSpec] = None,
) -> SwarmReport:
    emit(verbose, "\n" + "=" * 60)
    emit(verbose, "  ADVERSARY SWARM — ALL PHASES INITIATING")
    emit(verbose, "=" * 60)
    active_spec = task_spec or load_task_spec()

    async def build_report(active_client: httpx.AsyncClient) -> SwarmReport:
        phases = await _run_phase_suite(active_client, base_url, verbose, active_spec)
        critical_failures = sum(1 for phase in phases if phase.critical)
        passed_phases = sum(1 for phase in phases if phase.passed)
        passed = critical_failures == 0
        verdict = "API secure: armor holds" if passed else "API compromised: critical failures detected"

        if verbose:
            emit(verbose, "\n" + "─" * 60)
            emit(verbose, "  BATTLE DAMAGE ASSESSMENT")
            emit(verbose, "─" * 60)
            for phase in phases:
                icon = "✓ SECURE" if phase.passed else "!! CRITICAL"
                emit(verbose, f"  {icon:<14} Phase {phase.phase_id} {phase.name}")
            emit(verbose, "")
            emit(verbose, f"  >> VERDICT: {verdict.upper()}")

        return SwarmReport(
            base_url=base_url,
            passed=passed,
            phases=phases,
            summary={
                "critical_failures": critical_failures,
                "passed_phases": passed_phases,
                "verdict": verdict,
            },
        )

    probe_client: Optional[httpx.AsyncClient] = client
    owns_client = client is None
    if probe_client is None:
        probe_client = httpx.AsyncClient()

    try:
        await probe_client.get(f"{base_url}/balance/user_1", timeout=httpx.Timeout(3.0))
    except Exception as error:
        unreachable = PhaseResult(
            phase_id=0,
            name="Connectivity",
            passed=False,
            critical=True,
            details=[f"Server unreachable: {error}"],
            metrics={},
        )
        return SwarmReport(
            base_url=base_url,
            passed=False,
            phases=[unreachable],
            summary={
                "critical_failures": 1,
                "passed_phases": 0,
                "verdict": "API compromised: server unreachable",
            },
        )
    try:
        return await build_report(probe_client)
    finally:
        if owns_client:
            await probe_client.aclose()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Mark II adversary swarm")
    parser.add_argument("--base-url", default="http://127.0.0.1:8111")
    parser.add_argument("--task-spec")
    parser.add_argument("--json", action="store_true", dest="json_mode")
    args = parser.parse_args()

    task_spec = load_task_spec(args.task_spec)
    report = await build_swarm_report(
        base_url=args.base_url,
        verbose=not args.json_mode,
        task_spec=task_spec,
    )
    if args.json_mode:
        print(json.dumps(report.to_dict()))
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
