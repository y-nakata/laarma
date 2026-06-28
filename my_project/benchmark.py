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

from unittest.mock import MagicMock, patch

from laarma import (
    AARMRuntime, Decision, EnvironmentContext, IdentityContext,
    IntentAlignment, MaintenanceWindow, Policy, load_policy,
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


class _IASpy:
    """
    実 IntentAlignment をラップし、evaluate() が呼ばれたかどうかだけを記録する計測用スパイ。

    PolicyEngine.evaluate() は DENY が確定する3経路（denied_tools / privilege_scope /
    静的ルールでの DENY）でのみ IntentAlignment を呼ばずに終端する。この呼び出しの有無を
    観測すれば、各ケースが pipeline モードで LLM 依存かどうかをルール変更に追従して
    判定できる（ベンチマーク側の計測のみで、IntentAlignment の挙動自体は変えない）。
    """
    def __init__(self, real: IntentAlignment) -> None:
        self._real = real
        self.called = False

    def evaluate(self, *args: Any, **kwargs: Any) -> AuthorizationResult:
        self.called = True
        return self._real.evaluate(*args, **kwargs)

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
    # True のとき、pipeline モードでの不一致は fail にせず informational として扱う
    # （expected_decision は policy-engine モードでの検証が主、pipeline での IA 上書きは別 issue 依存）
    pipeline_informational: bool = False
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
                pipeline_only=data.get("pipeline_only", False),
                pipeline_informational=data.get("pipeline_informational", False),
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
) -> tuple[Decision | None, dict[str, Any] | None, float, str, str | None, dict | None, bool]:
    """
    Returns (decision, modified_params, elapsed_seconds, status, reason, context_summary, ia_invoked).
    status: "run" | "skip"
    ia_invoked: pipeline モードで IntentAlignment.evaluate() が実際に呼ばれたか
                （policy-engine モードでは常に False — スタブで代用するため計測不要）。
    """
    expected = Decision(case.expected_decision)

    # policy-engine モードでは LLM 判断が必要なケースをスキップ
    if mode == "policy-engine" and (
        expected not in _POLICY_ENGINE_DECISIONS or case.pipeline_only
    ):
        return None, None, 0.0, "skip", None, None, False

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
    # AARMRuntime のデフォルト解決 (model or AARM_MODEL or claude-sonnet-4-6) を計測用にも合わせる
    ia_spy = (
        _IASpy(IntentAlignment(model=model or os.getenv("AARM_MODEL", "claude-sonnet-4-6")))
        if mode == "pipeline" else None
    )
    runtime = AARMRuntime(
        user_intent=case.user_intent,
        identity=identity,
        environment=env,
        model=model,
        policy=policy,
        transform_registry=transform_registry,
        _skip_intent_alignment_for_testing=(mode == "policy-engine"),
        _intent_alignment=(_AlwaysAllowStub() if mode == "policy-engine" else ia_spy),
    )
    start = time.monotonic()
    result = runtime.intercept(case.action["tool_name"], case.action["parameters"])
    elapsed = time.monotonic() - start
    ia_invoked = ia_spy.called if ia_spy is not None else False
    return (
        result.decision, result.modified_params, elapsed, "run", result.reason,
        runtime.context_summary, ia_invoked,
    )


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


def _fake_llm_text_response(text: str) -> MagicMock:
    """anthropic.Anthropic().messages.create() の戻り値を模した MagicMock。"""
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    return resp


def run_intent_alignment_anomaly_unit_tests() -> int:
    """
    IntentAlignment.evaluate() の出力バリデーション（#88）をユニットレベルで検証する。
    anthropic クライアントをモックし、LLM の異常応答・呼び出し失敗が
    すべて DENY に収束すること（DEFER フォールバックが残っていないこと）を確認する。

    Returns: 失敗ケース数（0 = 全 PASS）。
    """
    _dummy_action = Action(tool_name="write_file", parameters={"path": "config.bak", "content": "x"})
    _context_summary = {
        "user_intent": "設定ファイルのバックアップを書き出して",
        "action_count": 0,
        "recent_actions": [],
        "derived_signals": {},
    }

    cases = [
        {
            "id": "ia_anomaly_modify_returned",
            "llm_text": '{"decision": "MODIFY", "reason": "should not happen", "modified_params": {"path": "x"}}',
            "raises": None,
            "reason_substr": "MODIFY を返してはならない",
        },
        {
            "id": "ia_anomaly_unknown_decision",
            "llm_text": '{"decision": "FOOBAR", "reason": "unknown"}',
            "raises": None,
            "reason_substr": "未知の decision 値",
        },
        {
            "id": "ia_anomaly_unparseable_response",
            "llm_text": "申し訳ありませんが対応できません。",
            "raises": None,
            "reason_substr": "応答を解釈できませんでした",
        },
        {
            "id": "ia_anomaly_client_call_fails",
            "llm_text": None,
            "raises": Exception("simulated max_retries exhausted"),
            "reason_substr": "LLM 呼び出しに失敗しました",
        },
    ]

    print("\n--- IntentAlignment anomaly → DENY unit tests (#88) ---")
    fail_count = 0
    for c in cases:
        ia = IntentAlignment()
        mock_client = MagicMock()
        if c["raises"] is not None:
            mock_client.messages.create.side_effect = c["raises"]
        else:
            mock_client.messages.create.return_value = _fake_llm_text_response(c["llm_text"])

        with patch.object(IntentAlignment, "_get_client", return_value=mock_client):
            result = ia.evaluate(_dummy_action, _context_summary, environment=None)

        ok = (
            result.decision == Decision.DENY
            and result.modified_params is None
            and c["reason_substr"] in result.reason
        )
        label = "✅" if ok else "❌"
        print(f"{label} {c['id']}")
        if not ok:
            print(f"   decision:        expected=DENY  actual={result.decision.value}")
            print(f"   modified_params: expected=None  actual={result.modified_params}")
            print(f"   reason contains '{c['reason_substr']}': actual={result.reason!r}")
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
    parser.add_argument(
        "--repeat", type=int, default=3,
        help=(
            "pipeline モードで IntentAlignment が実際に関与したケースのみ、安定性計測のため"
            "この回数だけ繰り返し実行する（default: 3）。IA を呼ばない決定論ケースや他モードは常に1回。"
        ),
    )
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
    unstable_count = 0
    summary: dict[str, int] = {d.value: 0 for d in Decision}
    mismatches: list[str] = []
    ia_passthrough_mismatches: list[str] = []
    pipeline_informational_mismatches: list[str] = []
    unstable_cases: list[tuple[str, int, int]] = []
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

    def _ok(decision: Decision, modified_params: dict | None, expected: str, case: BenchmarkCase) -> bool:
        return (
            decision.value == expected
            and compare_modified_params(modified_params, case.expected_modified_params)
        )

    for case in cases:
        run = run_case(case, mode=mode, model=args.model)
        decision, modified_params, elapsed, status, reason, context, ia_invoked = run

        if status == "skip":
            skip_count += 1
            if args.verbose:
                print(f"Case: {case.id}  [SKIP — not decidable by PolicyEngine alone]")
            continue

        expected = case.expected_decision
        runs = [run]
        # 安定性計測は pipeline モードで IntentAlignment が実際に関与したケースのみ。
        # 決定論ケース（denied_tools/privilege_scope/静的 DENY ルールで終端）は1回で確定する。
        repeat_n = args.repeat if (mode == "pipeline" and ia_invoked) else 1
        for _ in range(repeat_n - 1):
            runs.append(run_case(case, mode=mode, model=args.model))

        total_time += sum(r[2] for r in runs)
        summary[decision.value] += 1

        oks = [_ok(r[0], r[1], expected, case) for r in runs]
        pass_n = sum(oks)
        total_n = len(runs)
        if pass_n == total_n:
            stability = "stable_pass"
        elif pass_n == 0:
            stability = "stable_fail"
        else:
            stability = "mixed"

        # policy-engine モードで PolicyEngine が ALLOW（= pass-through）を返したが
        # 期待値が DENY/STEP_UP の場合は「IntentAlignment が担うべき判断」であり
        # PolicyEngine の正常動作。strict fail ではなく informational として扱う。
        ia_passthrough = (
            mode == "policy-engine"
            and decision == Decision.ALLOW
            and expected in (Decision.DENY, Decision.STEP_UP, Decision.DEFER)
        )
        # pipeline_informational ケース（例: defer_production_delete）は、expected_decision の
        # 検証主体が policy-engine モードであり、pipeline での不一致は #94 の射程（IA 上書き）の
        # ため fail にしない。ただし実際の decision はサマリに残し、症状を追跡可能にする。
        pipeline_informational_mismatch = (
            mode == "pipeline" and case.pipeline_informational and stability != "stable_pass"
        )

        if stability == "stable_pass":
            pass_count += 1
        elif stability == "mixed":
            unstable_count += 1
            unstable_cases.append((case.id, pass_n, total_n))
        elif ia_passthrough:
            inform_count += 1
            ia_passthrough_mismatches.append(case.id)
        elif pipeline_informational_mismatch:
            inform_count += 1
            pipeline_informational_mismatches.append(
                f"{case.id} (expected={expected}, actual={decision.value})"
            )
        elif strict_mode:
            fail_count += 1
            mismatches.append(case.id)
        else:
            mismatches.append(case.id)

        informational = ia_passthrough or pipeline_informational_mismatch
        # ia_passthrough（policy-engine の ALLOW pass-through）は元から非表示。
        # pipeline_informational の不一致は informational でも実際の decision を可視化するため表示する。
        if args.verbose or (stability != "stable_pass" and not ia_passthrough):
            if stability == "mixed":
                label = "🔀"
            elif stability == "stable_pass":
                label = "✅"
            elif informational:
                label = "ℹ️ "
            elif not strict_mode:
                label = "⚠️"
            else:
                label = "❌"
            print(f"{label} Case: {case.id}")
            print(f"  user_intent: {case.user_intent}")
            print(f"  action: {case.action}")
            print(f"  expected: {case.expected_decision}")
            print(f"  actual:   {decision.value}")
            if total_n > 1:
                print(f"  stability: {pass_n}/{total_n} pass ({stability})")
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
    if unstable_count:
        print(f"  unstable:      {unstable_count}  (mixed pass/fail across repeated runs — nondeterminism, not a regression)")
    if inform_count:
        print(f"  informational: {inform_count}  (see breakdown below — not counted as fail)")
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

    if ia_passthrough_mismatches:
        print("\nInformational — PolicyEngine pass-through (IntentAlignment would decide):")
        for case_id in ia_passthrough_mismatches:
            print(f"  - {case_id}")

    if pipeline_informational_mismatches:
        print("\nInformational — pipeline_informational cases (expected_decision is authoritative only in "
              "policy-engine mode; pipeline mismatch is tracked here, not counted as fail):")
        for entry in pipeline_informational_mismatches:
            print(f"  - {entry}")

    if unstable_cases:
        print("\nUnstable cases (mixed pass/fail across repeated runs — nondeterminism, not a regression):")
        for case_id, pass_n, total_n in unstable_cases:
            print(f"  - {case_id}: {pass_n}/{total_n} pass")

    if mode == "intent-alignment":
        print("\nNote: intent-alignment mode is exploratory; mismatches do not cause a nonzero exit status.")

    step_up_fail_count = run_step_up_unit_tests()
    ia_anomaly_fail_count = run_intent_alignment_anomaly_unit_tests()
    return 1 if (fail_count or step_up_fail_count or ia_anomaly_fail_count) else 0


if __name__ == "__main__":
    raise SystemExit(main())
