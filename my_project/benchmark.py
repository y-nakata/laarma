"""Benchmark runner for AARM pipeline layers.

Usage:
  pip install -e laarma_sdk
  export ANTHROPIC_API_KEY=your_api_key
  python my_project/benchmark.py                       # pipeline mode (default)
  python my_project/benchmark.py --mode policy-engine  # PolicyEngine only, no LLM
  python my_project/benchmark.py --pure-intent-alignment  # raw LLM judgment

Modes:
  pipeline (default)
    Full PolicyEngine + IntentAlignment pipeline with policy.yaml.
    Tests the system as deployed.

  policy-engine  (--mode policy-engine)
    Skip IntentAlignment entirely. Tests PolicyEngine rules in isolation.
    No API calls — fast deterministic regression test.
    Cases whose expected decision is ALLOW or STEP_UP are SKIP
    (PolicyEngine cannot produce these).

  intent-alignment  (--pure-intent-alignment / --mode intent-alignment)
    Bypass PolicyEngine configurable rules (keep denied_tools only).
    Disable confidence/scope-expansion pre-checks in IntentAlignment.
    Tests the LLM's raw semantic judgment. Mismatches are informational only.
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

from laarma import (
    AARMRuntime, Decision, EnvironmentContext, IdentityContext,
    MaintenanceWindow, Policy, load_policy,
)
from laarma.models import Action, AuthorizationResult
from laarma.policy_engine import DEFAULT_POLICY
from laarma.step_up_resolver import StepUpResolver
from my_project.identity_keys import load_or_create_keypair

# R6: Human/Agent/Service の3鍵で署名する（demo.py と同じ自己生成鍵の方式）。
# agent_identity は service_identity と紛らわしくならないよう instance id 風の値にする。
_KEYS_DIR = Path(__file__).resolve().parent.parent / "keys"
os.environ.setdefault("AARM_IDENTITY_PUBKEY_DIR", str(_KEYS_DIR))
_BENCHMARK_HUMAN_KEY   = load_or_create_keypair(_KEYS_DIR, "benchmark@local")
_BENCHMARK_AGENT_KEY   = load_or_create_keypair(_KEYS_DIR, "benchmark-agent-instance")
_BENCHMARK_SERVICE_KEY = load_or_create_keypair(_KEYS_DIR, "benchmark-runner")


class _AlwaysAllowStub:
    """policy-engine モード用スタブ。IntentAlignment を使わず常に ALLOW を返す。"""
    def evaluate(
        self,
        action: Action,
        context_summary: dict,
        environment: Any = None,
    ) -> AuthorizationResult:
        return AuthorizationResult(decision=Decision.ALLOW, reason="stub", action=action)

# path 変換のドメイン知識。policy.yaml の modify_transform が参照する。
_TRANSFORM_REGISTRY: dict[str, Any] = {
    "basename":    os.path.basename,
    "to_relative": lambda p: "./" + p.lstrip("/"),
}

# PolicyEngine のみが判断できる decision セット
_POLICY_ENGINE_DECISIONS = {Decision.DENY, Decision.DEFER, Decision.MODIFY}


@dataclass
class BenchmarkCase:
    id: str
    user_intent: str
    action: dict[str, Any]
    environment: dict[str, Any]
    expected_decision: str
    expected_modified_params: dict[str, Any] | None
    identity: dict[str, Any] | None = None
    pipeline_only: bool = False  # True のとき policy-engine モードでスキップ


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
                pipeline_only=data.get("pipeline_only", False),
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


def _build_policy(mode: str) -> tuple[Policy, dict]:
    """モードに応じた Policy と transform_registry を返す。"""
    policy_path = Path(__file__).parent / "policies" / "policy.yaml"

    if mode == "pipeline":
        return load_policy(policy_path), _TRANSFORM_REGISTRY

    if mode == "intent-alignment":
        # PolicyEngine の configurable rules を空にする。denied_tools は安全上の理由で残す。
        policy = Policy(
            denied_tools=set(DEFAULT_POLICY.denied_tools),
            required_params={},
            max_actions=999,
            rules=[],
        )
        return policy, {}

    if mode == "policy-engine":
        return load_policy(policy_path), _TRANSFORM_REGISTRY

    raise ValueError(f"Unknown mode: {mode}")


def run_case(
    case: BenchmarkCase,
    mode: str = "pipeline",
    model: str | None = None,
) -> tuple[Decision | None, dict[str, Any] | None, float, str, str | None, dict | None]:
    """
    Returns (decision, modified_params, elapsed_seconds, status, reason, context_summary).
    status: "run" | "skip"
    """
    expected = Decision(case.expected_decision)

    # policy-engine モードでは LLM 判断が必要なケースをスキップ
    if mode == "policy-engine" and (
        expected not in _POLICY_ENGINE_DECISIONS or case.pipeline_only
    ):
        return None, None, 0.0, "skip", None, None

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
    policy, transform_registry = _build_policy(mode)
    runtime = AARMRuntime(
        user_intent=case.user_intent,
        identity=identity,
        environment=env,
        model=model,
        policy=policy,
        transform_registry=transform_registry,
        _skip_intent_alignment_for_testing=(mode == "policy-engine"),
        _intent_alignment=(_AlwaysAllowStub() if mode == "policy-engine" else None),
    )
    start = time.monotonic()
    result = runtime.intercept(case.action["tool_name"], case.action["parameters"])
    elapsed = time.monotonic() - start
    return result.decision, result.modified_params, elapsed, "run", result.reason, runtime.context_summary


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
    parser = argparse.ArgumentParser(description="Run AARM benchmark cases.")
    parser.add_argument("--data-file", default="benchmark_data.jsonl", help="Benchmark dataset JSONL file")
    parser.add_argument("--model", default=None, help="Claude model to use for IntentAlignment")
    parser.add_argument(
        "--mode",
        choices=["pipeline", "intent-alignment", "policy-engine"],
        default="pipeline",
        help=(
            "pipeline: full PolicyEngine + IntentAlignment (default); "
            "intent-alignment: raw LLM judgment, bypass configurable rules; "
            "policy-engine: PolicyEngine only, no LLM"
        ),
    )
    # 後方互換エイリアス
    parser.add_argument("--pure-intent-alignment", action="store_true",
                        help="Alias for --mode intent-alignment (backwards compatible)")
    parser.add_argument("--verbose", action="store_true", help="Show detailed case output")
    args = parser.parse_args()

    mode = args.mode
    if args.pure_intent_alignment:
        mode = "intent-alignment"

    data_path = Path(__file__).resolve().parent / args.data_file
    if not data_path.exists():
        print(f"ERROR: benchmark data file not found: {data_path}")
        return 1

    cases = load_cases(data_path)
    total_time = 0.0
    pass_count = 0
    fail_count = 0
    skip_count = 0
    inform_count = 0
    summary: dict[str, int] = {d.value: 0 for d in Decision}
    mismatches: list[str] = []
    inform_mismatches: list[str] = []
    strict_mode = (mode != "intent-alignment")

    print(f"Loaded {len(cases)} benchmark cases from {data_path}")
    print(f"Mode: {mode}")
    if mode != "policy-engine":
        print(f"Model: {args.model or os.getenv('AARM_MODEL', 'default')}")
    if mode == "intent-alignment":
        print("Note: intent-alignment mode tests raw LLM judgment; mismatches are informational only.")
    if mode == "policy-engine":
        print("Note: policy-engine mode skips ALLOW/STEP_UP cases (not decidable without IntentAlignment).")
    print()

    for case in cases:
        decision, modified_params, elapsed, status, reason, context = run_case(case, mode=mode, model=args.model)

        if status == "skip":
            skip_count += 1
            if args.verbose:
                print(f"Case: {case.id}  [SKIP — not decidable by PolicyEngine alone]")
            continue

        total_time += elapsed
        summary[decision.value] += 1
        expected = case.expected_decision
        ok = decision.value == expected and compare_modified_params(modified_params, case.expected_modified_params)

        # policy-engine モードで PolicyEngine が ALLOW（= pass-through）を返したが
        # 期待値が DENY/STEP_UP の場合は「IntentAlignment が担うべき判断」であり
        # PolicyEngine の正常動作。strict fail ではなく informational として扱う。
        ia_passthrough = (
            mode == "policy-engine"
            and decision == Decision.ALLOW
            and expected in (Decision.DENY, Decision.STEP_UP, Decision.DEFER)
        )

        if ok:
            pass_count += 1
        elif ia_passthrough:
            inform_count += 1
            inform_mismatches.append(case.id)
        elif strict_mode:
            fail_count += 1
            mismatches.append(case.id)
        else:
            mismatches.append(case.id)

        if args.verbose or (not ok and not ia_passthrough):
            label = "✅" if ok else ("ℹ️ " if ia_passthrough else ("⚠️" if not strict_mode else "❌"))
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

    run_count = len(cases) - skip_count
    print("Benchmark summary:")
    print(f"  cases:         {len(cases)}")
    print(f"  run:           {run_count}")
    print(f"  skip:          {skip_count}")
    print(f"  pass:          {pass_count}")
    print(f"  fail:          {fail_count}")
    if inform_count:
        print(f"  informational: {inform_count}  (PolicyEngine pass-through — IntentAlignment would decide)")
    if run_count > 0:
        print(f"  total time:    {total_time:.2f}s")
        print(f"  avg time/case: {total_time / run_count:.2f}s")
    print("  decisions:")
    for d, count in summary.items():
        if count:
            print(f"    {d}: {count}")

    if mismatches:
        label = "Mismatched cases" if strict_mode else "Informational mismatches"
        print(f"\n{label}:")
        for case_id in mismatches:
            print(f"  - {case_id}")

    if inform_mismatches:
        print("\nInformational (PolicyEngine pass-through — expected IntentAlignment to decide):")
        for case_id in inform_mismatches:
            print(f"  - {case_id}")

    if mode == "intent-alignment":
        print("\nNote: intent-alignment mode is exploratory; mismatches do not cause a nonzero exit status.")

    step_up_fail_count = run_step_up_unit_tests()
    return 1 if (fail_count or step_up_fail_count) else 0


if __name__ == "__main__":
    raise SystemExit(main())
