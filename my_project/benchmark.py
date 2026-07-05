"""Benchmark runner for the AARM PolicyEngine.

Usage:
  pip install -e laarma_sdk
  python my_project/benchmark.py

Phase A (#112) removed the LLM-based decision layer (IntentAlignment) entirely.
PolicyEngine.evaluate() is now the sole, deterministic decision path — there is
no LLM call in it, so this runner has a single mode and needs no API key.
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

from unittest.mock import patch

from laarma import AARMRuntime, Decision, EnvironmentContext, IdentityContext, MaintenanceWindow, load_policy
from laarma.models import Action, AuthorizationResult
from laarma.step_up_resolver import StepUpResolver
from my_project.identity_keys import load_or_create_keypair

# R6: Human/Agent/Service の3鍵で署名する（demo.py と同じ自己生成鍵の方式）。
# agent_identity は service_identity と紛らわしくならないよう instance id 風の値にする。
_KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"
os.environ.setdefault("AARM_IDENTITY_PUBKEY_DIR", str(_KEYS_DIR))
_BENCHMARK_HUMAN_KEY   = load_or_create_keypair(_KEYS_DIR, "benchmark@local")
_BENCHMARK_AGENT_KEY   = load_or_create_keypair(_KEYS_DIR, "benchmark-agent-instance")
_BENCHMARK_SERVICE_KEY = load_or_create_keypair(_KEYS_DIR, "benchmark-runner")

# path 変換のドメイン知識。policy.yaml の modify_transform が参照する。
_TRANSFORM_REGISTRY: dict[str, Any] = {
    "basename":    os.path.basename,
    "to_relative": lambda p: "./" + p.lstrip("/"),
}

_POLICY_PATH = Path(__file__).parent / "policies" / "policy.yaml"


@dataclass
class BenchmarkCase:
    id: str
    user_intent: str
    action: dict[str, Any]
    environment: dict[str, Any]
    expected_decision: str
    expected_modified_params: dict[str, Any] | None
    identity: dict[str, Any] | None = None
    # 非 None のとき、expected_decision とのミスマッチは fail ではなく informational として
    # 扱う（値は「いつ回復する見込みか」の注記、例: "Phase B"。ロジックには使わない）。
    known_regression_until: str | None = None
    note: str | None = None  # ケースの検証意図・素性の説明（ロジックには使わない）


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
                identity=data.get("identity"),
                known_regression_until=data.get("known_regression_until"),
                note=data.get("note"),
            ))
    return cases


def build_environment(env: dict[str, Any]) -> EnvironmentContext:
    windows = [MaintenanceWindow(**w) for w in env.get("maintenance_windows", [])]
    return EnvironmentContext(
        environment=env.get("environment", "production"),
        maintenance_windows=windows,
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


def run_case(case: BenchmarkCase) -> tuple[Decision, dict[str, Any] | None, float, str | None, dict]:
    """Returns (decision, modified_params, elapsed_seconds, reason, context_summary)."""
    env = build_environment(case.environment)
    # case に identity.privilege_scope があればそれを使い、なければ評価対象ツールのみ許可する
    # （デフォルトはツールが必ずスコープ内になるため privilege_scope DENY は発火しない）
    if case.identity and "privilege_scope" in case.identity:
        privilege_scope = case.identity["privilege_scope"]
    else:
        privilege_scope = [case.action["tool_name"]]
    identity = IdentityContext(
        human_principal="benchmark@local",
        agent_identity="benchmark-agent-instance",
        service_identity="benchmark-runner",
        session_id=case.id,
        privilege_scope=privilege_scope,
    )
    # R6: 未署名だと AARMRuntime が警告を出す
    identity = (
        identity
        .sign_human(_BENCHMARK_HUMAN_KEY)
        .sign_agent(_BENCHMARK_AGENT_KEY)
        .sign_service(_BENCHMARK_SERVICE_KEY)
    )
    policy = load_policy(_POLICY_PATH)
    runtime = AARMRuntime(
        user_intent=case.user_intent,
        identity=identity,
        environment=env,
        policy=policy,
        transform_registry=_TRANSFORM_REGISTRY,
    )
    start = time.monotonic()
    result = runtime.intercept(case.action["tool_name"], case.action["parameters"])
    elapsed = time.monotonic() - start
    return result.decision, result.modified_params, elapsed, result.reason, runtime.context_summary


def run_step_up_unit_tests() -> int:
    """
    StepUpResolver の承認後動作をユニットレベルで検証する。
    builtins.input をパッチして対話的入力を注入する。

    Returns: 失敗ケース数（0 = 全 PASS）。
    """
    # nosec B108 — write_file は my_project のデモ用スタブ（tools.py）で、文字列を返すのみで
    # ファイルを作らない。/tmp/x はそのスタブに渡るダミー引数のため B108（予測可能な temp
    # ファイル名でのファイル生成）は該当しない。bandit は文字列リテラルのみを見て誤検知する。
    _dummy_action = Action(tool_name="write_file", parameters={"path": "/tmp/x", "content": "hi"})  # nosec B108

    cases = [
        {
            "id": "step_up_no_modified_params_approved",
            "input": "y",
            "modified_params": None,
            "expected_decision": Decision.ALLOW,
            "expected_resolution_method": "human_approved",
            "expected_modified_params": None,
        },
        {
            "id": "step_up_with_modified_params_approved",
            "input": "y",
            "modified_params": {"path": "safe.txt", "content": "hi"},
            "expected_decision": Decision.MODIFY,
            "expected_resolution_method": "human_approved",
            "expected_modified_params": {"path": "safe.txt", "content": "hi"},
        },
        {
            "id": "step_up_with_modified_params_denied",
            "input": "n",
            "modified_params": {"path": "safe.txt", "content": "hi"},
            "expected_decision": Decision.DENY,
            "expected_resolution_method": "human_denied",
            "expected_modified_params": None,  # DENY では不問
        },
    ]

    print("\n--- StepUpResolver unit tests ---")
    fail_count = 0
    for c in cases:
        step_up_result = AuthorizationResult(
            decision=Decision.STEP_UP,
            reason="テスト用 STEP_UP",
            action=_dummy_action,
            modified_params=c["modified_params"],
        )
        with patch("builtins.input", return_value=c["input"]):
            resolved = StepUpResolver().resolve(step_up_result)

        ok = (
            resolved.decision == c["expected_decision"]
            and resolved.resolution_method == c["expected_resolution_method"]
            and (
                c["expected_modified_params"] is None
                or resolved.modified_params == c["expected_modified_params"]
            )
        )
        label = "✅" if ok else "❌"
        print(f"{label} {c['id']}")
        if not ok:
            print(f"   decision:          expected={c['expected_decision'].value}  actual={resolved.decision.value}")
            print(f"   resolution_method: expected={c['expected_resolution_method']}  actual={resolved.resolution_method}")
            if c["expected_modified_params"] is not None:
                print(f"   modified_params:   expected={c['expected_modified_params']}  actual={resolved.modified_params}")
            fail_count += 1

    total = len(cases)
    print(f"{total - fail_count} passed, {fail_count} failed\n")
    return fail_count


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AARM PolicyEngine benchmark cases.")
    parser.add_argument("--data-file", default="benchmark_data.jsonl", help="Benchmark dataset JSONL file")
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
    inform_count = 0
    summary: dict[str, int] = {d.value: 0 for d in Decision}
    mismatches: list[str] = []
    known_regression_mismatches: list[str] = []

    print(f"Loaded {len(cases)} benchmark cases from {data_path}")
    print()

    for case in cases:
        decision, modified_params, elapsed, reason, context = run_case(case)
        total_time += elapsed
        summary[decision.value] += 1

        ok = (
            decision.value == case.expected_decision
            and compare_modified_params(modified_params, case.expected_modified_params)
        )
        known_regression = case.known_regression_until is not None and not ok

        if ok:
            pass_count += 1
        elif known_regression:
            inform_count += 1
            known_regression_mismatches.append(
                f"{case.id} (expected={case.expected_decision}, actual={decision.value}, "
                f"until={case.known_regression_until})"
            )
        else:
            fail_count += 1
            mismatches.append(case.id)

        if args.verbose or not ok:
            if ok:
                label = "✅"
            elif known_regression:
                label = "🚧"
            else:
                label = "❌"
            print(f"{label} Case: {case.id}")
            print(f"  user_intent: {case.user_intent}")
            print(f"  action: {case.action}")
            print(f"  expected: {case.expected_decision}")
            print(f"  actual:   {decision.value}")
            if reason:
                print(f"  reason:   {reason}")
            if case.expected_modified_params or modified_params:
                print(f"  expected_modified_params: {case.expected_modified_params}")
                print(f"  actual_modified_params:   {modified_params}")
            if args.verbose and context:
                sig = context.get("derived_signals", {})
                sd = sig.get("semantic_distance", {})
                print(f"  semantic_distance: avg={sd.get('average', '—')} current={sd.get('current', '—')}")
                print(f"  confidence:        {sig.get('confidence_level', '—')}")
                dc = sig.get("data_classifications", [])
                if dc:
                    print(f"  data_classifications: {dc}")
            print(f"  elapsed: {elapsed:.2f}s\n")

    print("Benchmark summary:")
    print(f"  cases:         {len(cases)}")
    print(f"  pass:          {pass_count}")
    print(f"  fail:          {fail_count}")
    if inform_count:
        print(f"  informational: {inform_count}  (known regressions, not counted as fail — see breakdown below)")
    print(f"  total time:    {total_time:.2f}s")
    print(f"  avg time/case: {total_time / len(cases):.2f}s")
    print("  decisions:")
    for d, count in summary.items():
        if count:
            print(f"    {d}: {count}")

    if mismatches:
        print("\nMismatched cases:")
        for case_id in mismatches:
            print(f"  - {case_id}")

    if known_regression_mismatches:
        print("\nInformational — known regressions (tracked, not counted as fail):")
        for entry in known_regression_mismatches:
            print(f"  - {entry}")

    step_up_fail_count = run_step_up_unit_tests()
    return 1 if (fail_count or step_up_fail_count) else 0


if __name__ == "__main__":
    raise SystemExit(main())
