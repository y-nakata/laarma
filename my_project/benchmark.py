"""Benchmark runner for AARM intent alignment and static policy behavior.

Usage:
  pip install -e aarm/laarma_sdk
  export ANTHROPIC_API_KEY=your_api_key
  python aarm/my_project/benchmark.py

This script loads benchmark_data.jsonl and evaluates each case through the
AARMRuntime pipeline, measuring execution time and decision consistency.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from laarma import AARMRuntime, Decision, EnvironmentContext, IdentityContext, MaintenanceWindow


@dataclass
class BenchmarkCase:
    id: str
    user_intent: str
    action: dict[str, Any]
    environment: dict[str, Any]
    expected_decision: str
    expected_modified_params: dict[str, Any] | None


def load_cases(path: Path) -> list[BenchmarkCase]:
    cases: list[BenchmarkCase] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            data = json.loads(line)
            cases.append(BenchmarkCase(
                id=data["id"],
                user_intent=data["user_intent"],
                action=data["action"],
                environment=data["environment"],
                expected_decision=data["expected_decision"],
                expected_modified_params=data.get("expected_modified_params"),
            ))
    return cases


def build_environment(env: dict[str, Any]) -> EnvironmentContext:
    windows = [MaintenanceWindow(**w) for w in env.get("maintenance_windows", [])]
    return EnvironmentContext(
        environment=env.get("environment", "production"),
        maintenance_windows=windows,
        high_sensitivity=env.get("high_sensitivity", False),
        custom=env.get("custom", {}),
    )


def _matches_expected_param(actual: Any, expected: Any) -> bool:
    if expected == "__any__":
        return True
    if expected == "__safe_path__":
        if not isinstance(actual, str):
            return False
        return not actual.startswith("/") and ".." not in actual
    return actual == expected


def compare_modified_params(actual: dict[str, Any] | None, expected: dict[str, Any] | None) -> bool:
    if expected is None:
        return actual is None or actual == {}
    if actual is None:
        return False
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        if not _matches_expected_param(actual[key], expected_value):
            return False
    return True


def run_case(
    case: BenchmarkCase,
    model: str | None = None,
    allow_intent_alignment_confidence_precheck: bool = True,
) -> tuple[Decision, dict[str, Any] | None, float]:
    env = build_environment(case.environment)
    identity = IdentityContext(
        human_principal="benchmark@local",
        service_identity="benchmark-runner",
        session_id=case.id,
        privilege_scope=[case.action["tool_name"]],
    )
    runtime = AARMRuntime(
        user_intent=case.user_intent,
        identity=identity,
        environment=env,
        model=model,
        allow_intent_alignment_confidence_precheck=allow_intent_alignment_confidence_precheck,
    )
    start = time.monotonic()
    result = runtime.intercept(case.action["tool_name"], case.action["parameters"])
    elapsed = time.monotonic() - start
    return result.decision, result.modified_params, elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AARM benchmark cases.")
    parser.add_argument("--data-file", default="benchmark_data.jsonl", help="Benchmark dataset JSONL file")
    parser.add_argument("--model", default=None, help="Claude model to use for IntentAlignment")
    parser.add_argument("--pure-intent-alignment", action="store_true", help="Disable IntentAlignment confidence-based prechecks and benchmark the raw LLM judgment")
    parser.add_argument("--verbose", action="store_true", help="Show detailed case output")
    args = parser.parse_args()

    data_path = Path(__file__).resolve().parent / args.data_file
    if not data_path.exists():
        print(f"ERROR: benchmark data file not found: {data_path}")
        return 1

    cases = load_cases(data_path)
    total_time = 0.0
    pass_count = 0
    fail_count = 0
    summary: dict[str, int] = {decision.value: 0 for decision in Decision}
    mismatches: list[str] = []
    strict_mode = not args.pure_intent_alignment

    print(f"Loaded {len(cases)} benchmark cases from {data_path}")
    print(f"Using IntentAlignment model: {args.model or os.getenv('AARM_MODEL', 'default')}")
    if args.pure_intent_alignment:
        print("Pure IntentAlignment mode: IntentAlignment confidence-based prechecks are disabled, and expectation mismatches are informational only.")
    print()

    for case in cases:
        decision, modified_params, elapsed = run_case(
            case,
            model=args.model,
            allow_intent_alignment_confidence_precheck=not args.pure_intent_alignment,
        )
        total_time += elapsed
        summary[decision.value] += 1
        expected = case.expected_decision
        ok = decision.value == expected and compare_modified_params(modified_params, case.expected_modified_params)
        if ok:
            pass_count += 1
        elif strict_mode:
            fail_count += 1
            mismatches.append(case.id)
        else:
            mismatches.append(case.id)

        if args.verbose or not ok:
            print(f"Case: {case.id}")
            print(f"  user_intent: {case.user_intent}")
            print(f"  action: {case.action}")
            print(f"  expected: {case.expected_decision}")
            print(f"  actual:   {decision.value}")
            print(f"  expected_modified_params: {case.expected_modified_params}")
            print(f"  actual_modified_params:   {modified_params}")
            print(f"  elapsed: {elapsed:.2f}s\n")

    print("Benchmark summary:")
    print(f"  cases:         {len(cases)}")
    print(f"  pass:          {pass_count}")
    print(f"  fail:          {fail_count}")
    print(f"  total time:    {total_time:.2f}s")
    print(f"  avg time/case: {total_time / len(cases):.2f}s")
    print("  decisions:")
    for decision, count in summary.items():
        print(f"    {decision}: {count}")

    if mismatches:
        print("\nMismatched cases:")
        for case_id in mismatches:
            print(f"  - {case_id}")

    if args.pure_intent_alignment:
        print("\nNote: Pure IntentAlignment mode is exploratory; expectation mismatches do not cause a nonzero exit status.")
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
