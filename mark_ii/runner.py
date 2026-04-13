from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from .config import (
    ASGI_BASE_URL,
    BASE_URL,
    MARK_II_DIR,
    PORT,
    SERVER_READY_INTERVAL_S,
    SERVER_READY_RETRIES,
    SMOKE_TIMEOUT_S,
    SWARM_TIMEOUT_S,
    VALIDATION_MODE,
)
from .schemas import PhaseResult, SwarmReport


def ensure_port_free(port: int = PORT) -> None:
    subprocess.run(f"lsof -ti:{port} | xargs kill -9 2>/dev/null; true", shell=True, check=False)
    time.sleep(0.2)


def run_syntax_check(file_path: Path) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(file_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True, "Syntax check passed"
    detail = (result.stderr or result.stdout or "Syntax check failed").strip()
    return False, detail


def start_server(file_path: Path) -> subprocess.Popen[str]:
    ensure_port_free()
    log_file = tempfile.NamedTemporaryFile(mode="w+", suffix=".log", delete=False)
    server = subprocess.Popen(
        [sys.executable, str(file_path)],
        stdout=log_file,
        stderr=log_file,
        text=True,
    )
    setattr(server, "_markii_log_file", log_file)
    return server


def _read_server_log(server: subprocess.Popen[str]) -> str:
    log_file = getattr(server, "_markii_log_file", None)
    if log_file is None:
        return ""
    log_file.flush()
    log_file.seek(0)
    return log_file.read().strip()


def wait_for_server(server: subprocess.Popen[str], base_url: str = BASE_URL) -> tuple[bool, str]:
    for _ in range(SERVER_READY_RETRIES):
        if server.poll() is not None:
            detail = _read_server_log(server) or "Server exited before startup check"
            return False, detail
        try:
            response = httpx.get(f"{base_url}/balance/user_1", timeout=1.0)
            if response.status_code < 500:
                return True, f"Server ready with status {response.status_code}"
        except Exception:
            pass
        time.sleep(SERVER_READY_INTERVAL_S)

    return False, "Timed out waiting for server startup"


def stop_server(server: subprocess.Popen[str] | None) -> None:
    if server is None:
        return
    if server.poll() is None:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=5)
    log_file = getattr(server, "_markii_log_file", None)
    if log_file is not None:
        log_file.close()
    ensure_port_free()


def run_smoke_suite(base_url: str = BASE_URL) -> tuple[bool, str, dict]:
    timeout = httpx.Timeout(SMOKE_TIMEOUT_S)
    metrics: dict[str, float | int | str] = {}

    try:
        with httpx.Client(timeout=timeout) as client:
            reset_response = client.post(f"{base_url}/reset")
            if reset_response.status_code != 200:
                return False, f"/reset returned {reset_response.status_code}", metrics

            transfer_response = client.post(
                f"{base_url}/transfer",
                json={"user_id": "user_1", "amount": 1.0},
            )
            if transfer_response.status_code != 200:
                return False, f"/transfer returned {transfer_response.status_code}", metrics

            balance_response = client.get(f"{base_url}/balance/user_1")
            if balance_response.status_code != 200:
                return False, f"/balance returned {balance_response.status_code}", metrics

            balance = balance_response.json().get("balance")
            if not isinstance(balance, (int, float)):
                return False, "Balance response was not numeric", metrics

            metrics["remaining_balance"] = float(balance)
            return True, f"Smoke suite passed with balance={balance}", metrics
    except Exception as error:
        return False, f"Smoke suite error: {error}", metrics


def run_swarm_report(base_url: str = BASE_URL) -> tuple[bool, SwarmReport | None, str]:
    command = [
        sys.executable,
        str(MARK_II_DIR / "swarm_strike.py"),
        "--base-url",
        base_url,
        "--json",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=SWARM_TIMEOUT_S,
    )
    stdout = result.stdout.strip()
    if not stdout:
        detail = (result.stderr or "Swarm returned no output").strip()
        return False, None, detail

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as error:
        detail = f"Could not parse swarm JSON: {error}"
        if result.stderr.strip():
            detail = f"{detail} | stderr={result.stderr.strip()}"
        return False, None, detail

    phases = [PhaseResult(**phase) for phase in payload.get("phases", [])]
    report = SwarmReport(
        base_url=payload.get("base_url", base_url),
        passed=payload.get("passed", False),
        phases=phases,
        summary=payload.get("summary", {}),
    )
    detail = payload.get("summary", {}).get("verdict", "Swarm run completed")
    return result.returncode == 0 and report.passed, report, detail


def _run_harness(candidate_path: Path, mode: str, timeout_s: float, task_spec_path: str | None = None) -> dict:
    command = [
        sys.executable,
        str(MARK_II_DIR / "asgi_harness.py"),
        "--candidate-path",
        str(candidate_path),
        "--mode",
        mode,
    ]
    if task_spec_path:
        command.extend(["--task-spec", task_spec_path])
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    stdout = result.stdout.strip()
    if not stdout:
        detail = (result.stderr or "Harness returned no output").strip()
        raise RuntimeError(detail)
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        detail = f"Could not parse harness JSON: {error}"
        if result.stderr.strip():
            detail = f"{detail} | stderr={result.stderr.strip()}"
        raise RuntimeError(detail) from error


def run_startup_check(candidate_path: Path, task_spec_path: str | None = None) -> tuple[bool, str, dict]:
    if VALIDATION_MODE != "asgi":
        raise RuntimeError(f"Unsupported MARK_II_VALIDATION_MODE={VALIDATION_MODE!r}; expected 'asgi'")
    payload = _run_harness(candidate_path, "startup", timeout_s=SMOKE_TIMEOUT_S, task_spec_path=task_spec_path)
    return payload.get("passed", False), payload.get("detail", "Startup check completed"), payload.get("metrics", {})


def run_openapi_check(candidate_path: Path, task_spec_path: str | None = None) -> tuple[bool, str, dict]:
    if VALIDATION_MODE != "asgi":
        raise RuntimeError(f"Unsupported MARK_II_VALIDATION_MODE={VALIDATION_MODE!r}; expected 'asgi'")
    payload = _run_harness(candidate_path, "openapi", timeout_s=SMOKE_TIMEOUT_S, task_spec_path=task_spec_path)
    return payload.get("passed", False), payload.get("detail", "OpenAPI check completed"), payload.get("metrics", {})


def run_candidate_smoke_suite(candidate_path: Path, task_spec_path: str | None = None) -> tuple[bool, str, dict]:
    if VALIDATION_MODE != "asgi":
        raise RuntimeError(f"Unsupported MARK_II_VALIDATION_MODE={VALIDATION_MODE!r}; expected 'asgi'")
    payload = _run_harness(candidate_path, "smoke", timeout_s=SMOKE_TIMEOUT_S, task_spec_path=task_spec_path)
    return payload.get("passed", False), payload.get("detail", "Smoke suite completed"), payload.get("metrics", {})


def run_candidate_swarm_report(candidate_path: Path, task_spec_path: str | None = None) -> tuple[bool, SwarmReport | None, str]:
    if VALIDATION_MODE != "asgi":
        raise RuntimeError(f"Unsupported MARK_II_VALIDATION_MODE={VALIDATION_MODE!r}; expected 'asgi'")
    payload = _run_harness(candidate_path, "swarm", timeout_s=SWARM_TIMEOUT_S, task_spec_path=task_spec_path)
    report_payload = payload.get("report", {})
    phases = [PhaseResult(**phase) for phase in report_payload.get("phases", [])]
    report = SwarmReport(
        base_url=report_payload.get("base_url", ASGI_BASE_URL),
        passed=report_payload.get("passed", False),
        phases=phases,
        summary=report_payload.get("summary", {}),
    )
    detail = payload.get("detail", report.summary.get("verdict", "Swarm run completed"))
    return payload.get("passed", False), report, detail
