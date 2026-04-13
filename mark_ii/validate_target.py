from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .validator import validate_code_snapshot


def _print_summary(source_name: str, evaluation) -> None:
    print(f"\nValidation summary for {source_name}")
    print(f"provider={evaluation.provider} model={evaluation.model}")
    print(
        f"accepted={evaluation.accepted} score={evaluation.score} "
        f"format={evaluation.candidate_format} lines_changed={evaluation.lines_changed}"
    )
    for check in evaluation.checks:
        status = "PASS" if check.passed else "FAIL"
        print(f"  - {check.name:<7} {status} | {check.detail}")
    if evaluation.failure_type:
        print(f"failure_type={evaluation.failure_type}")
    if evaluation.rejection_reason:
        print(f"rejection_reason={evaluation.rejection_reason}")
    if evaluation.swarm_report is not None:
        print("swarm phases:")
        for phase in evaluation.swarm_report.phases:
            verdict = "PASS" if phase.passed else "FAIL"
            print(f"  - phase {phase.phase_id}: {verdict} | {phase.name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Mark II validator against a target file")
    parser.add_argument("--file", default=str(Path(__file__).resolve().parent / "target_api.py"))
    parser.add_argument("--task-spec")
    parser.add_argument("--provider", default="Manual")
    parser.add_argument("--model", default="manual-check")
    parser.add_argument("--json", action="store_true", dest="json_mode")
    args = parser.parse_args()

    target_path = Path(args.file).resolve()
    if args.json_mode:
        os.environ["STARK_LOG_STDOUT"] = "0"
    code = target_path.read_text()
    evaluation = validate_code_snapshot(
        code=code,
        source_name=target_path.name,
        provider=args.provider,
        model=args.model,
        task_spec_path=args.task_spec,
    )

    if args.json_mode:
        print(json.dumps(evaluation.to_summary(), indent=2))
    else:
        _print_summary(target_path.name, evaluation)
    return 0 if evaluation.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
