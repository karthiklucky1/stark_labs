from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import ASGI_BASE_URL
from swarm_strike import build_swarm_report
from .task_spec import TaskSpec, load_task_spec


TYPE_CHECKERS: dict[str, tuple[type[Any], ...]] = {
    "number": (int, float),
    "string": (str,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def _load_app(candidate_path: Path):
    module_name = f"markii_candidate_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, candidate_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load candidate module from {candidate_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    app = getattr(module, "app", None)
    if app is None:
        raise RuntimeError("Candidate module does not expose an 'app' object")
    return app


async def _openapi_check(client: httpx.AsyncClient, task_spec: TaskSpec) -> tuple[bool, str, dict]:
    response = await client.get("/openapi.json")
    if response.status_code != 200:
        return False, f"/openapi.json returned {response.status_code}", {}

    payload = response.json()
    paths = payload.get("paths", {})
    details: list[str] = []
    for route in task_spec.required_routes:
        schema_methods = {method.upper() for method in paths.get(route.path, {}).keys()}
        required_methods = {method.upper() for method in route.methods}
        if not required_methods.issubset(schema_methods):
            details.append(f"missing {route.path} methods={sorted(required_methods)}")

    metrics = {
        "documented_paths": len(paths),
        "title": payload.get("info", {}).get("title", ""),
    }
    if details:
        return False, "OpenAPI schema is missing required routes", {"errors": details, **metrics}
    return True, "OpenAPI schema includes required routes", metrics


async def _startup_check(candidate_path: Path, task_spec: TaskSpec) -> dict:
    app = _load_app(candidate_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ASGI_BASE_URL, timeout=httpx.Timeout(5.0)) as client:
        openapi_ok, openapi_detail, openapi_metrics = await _openapi_check(client, task_spec)
        route_count = len(getattr(app, "routes", []))
    return {
        "passed": True,
        "detail": "ASGI app imported successfully",
        "metrics": {
            "route_count": route_count,
            "openapi_ok": openapi_ok,
            "openapi_detail": openapi_detail,
            **openapi_metrics,
        },
    }


async def _run_openapi(candidate_path: Path, task_spec: TaskSpec) -> dict:
    app = _load_app(candidate_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ASGI_BASE_URL, timeout=httpx.Timeout(5.0)) as client:
        passed, detail, metrics = await _openapi_check(client, task_spec)
    return {"passed": passed, "detail": detail, "metrics": metrics}


def _extract_json_value(payload: Any, dotted_path: str) -> Any:
    current = payload
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(dotted_path)
        current = current[part]
    return current


async def _run_smoke(candidate_path: Path, task_spec: TaskSpec) -> dict:
    app = _load_app(candidate_path)
    transport = httpx.ASGITransport(app=app)
    metrics: dict[str, float | int | str] = {}

    async with httpx.AsyncClient(transport=transport, base_url=ASGI_BASE_URL, timeout=httpx.Timeout(5.0)) as client:
        for step in task_spec.smoke_steps:
            response = await client.request(
                step.method,
                step.path,
                json=step.json_body,
                headers=step.headers,
            )
            if response.status_code not in step.expected_statuses:
                return {
                    "passed": False,
                    "detail": f"{step.name} returned {response.status_code}; expected {step.expected_statuses}",
                    "metrics": metrics,
                }

            if step.expect_json_field is not None:
                try:
                    payload = response.json()
                    value = _extract_json_value(payload, step.expect_json_field)
                except Exception as error:
                    return {
                        "passed": False,
                        "detail": f"{step.name} could not read {step.expect_json_field}: {error}",
                        "metrics": metrics,
                    }
                if step.expect_json_type is not None:
                    expected_types = TYPE_CHECKERS[step.expect_json_type]
                    if not isinstance(value, expected_types):
                        return {
                            "passed": False,
                            "detail": f"{step.name} field {step.expect_json_field} was not {step.expect_json_type}",
                            "metrics": metrics,
                        }
                if step.expect_json_equals is not None and value != step.expect_json_equals:
                    return {
                        "passed": False,
                        "detail": f"{step.name} field {step.expect_json_field} was {value!r}, expected {step.expect_json_equals!r}",
                        "metrics": metrics,
                    }
                if step.save_metric_as is not None:
                    metrics[step.save_metric_as] = value

    return {
        "passed": True,
        "detail": "Smoke suite passed",
        "metrics": metrics,
    }


async def _run_swarm(candidate_path: Path, task_spec: TaskSpec) -> dict:
    app = _load_app(candidate_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=ASGI_BASE_URL) as client:
        report = await build_swarm_report(
            base_url=ASGI_BASE_URL,
            verbose=False,
            client=client,
            task_spec=task_spec,
        )
    return {
        "passed": report.passed,
        "detail": report.summary.get("verdict", "Swarm run completed"),
        "report": report.to_dict(),
    }


async def _dispatch(mode: str, candidate_path: Path, task_spec: TaskSpec) -> dict:
    if mode == "startup":
        return await _startup_check(candidate_path, task_spec)
    if mode == "openapi":
        return await _run_openapi(candidate_path, task_spec)
    if mode == "smoke":
        return await _run_smoke(candidate_path, task_spec)
    if mode == "swarm":
        return await _run_swarm(candidate_path, task_spec)
    raise RuntimeError(f"Unsupported mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Mark II ASGI validation against a candidate file")
    parser.add_argument("--candidate-path", required=True)
    parser.add_argument("--task-spec")
    parser.add_argument("--mode", choices=["startup", "openapi", "smoke", "swarm"], required=True)
    args = parser.parse_args()

    candidate_path = Path(args.candidate_path).resolve()
    task_spec = load_task_spec(args.task_spec)
    try:
        result = asyncio.run(_dispatch(args.mode, candidate_path, task_spec))
    except Exception as error:
        traceback.print_exc(file=sys.stderr)
        print(
            json.dumps(
                {
                    "passed": False,
                    "detail": str(error),
                    "metrics": {},
                }
            )
        )
        return 1

    print(json.dumps(result))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
