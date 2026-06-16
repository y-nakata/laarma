"""
ポリシーファイル読み込み機構

YAML または JSON のポリシーファイルを読み込み Policy オブジェクトを返す。
ポリシーファイルは SDK 本体とは独立して管理でき、
プロジェクト側 (my_project/policies/) に配置する。
"""

from __future__ import annotations

import json
from pathlib import Path

from .policy_engine import Policy, StaticRule


def load_policy(path: str | Path) -> Policy:
    """
    ポリシーファイル (.yaml/.yml/.json) を読み込んで Policy を返す。

    Parameters
    ----------
    path : str | Path
        ポリシーファイルのパス。

    Returns
    -------
    Policy
        読み込んだポリシー。

    Raises
    ------
    FileNotFoundError
        ファイルが存在しない場合。
    ValueError
        未対応のファイル形式の場合。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"ポリシーファイルが見つかりません: {p}")

    suffix = p.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise ImportError("YAML ポリシーファイルの読み込みには pyyaml が必要です: pip install pyyaml") from exc
        data: dict = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    elif suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
    else:
        raise ValueError(f"未対応のポリシーファイル形式: {suffix!r}  (対応: .yaml, .yml, .json)")

    rules = [
        StaticRule(
            id=r["id"],
            decision=r["decision"],
            reason=r["reason"],
            conditions=r.get("conditions", {}),
            modify_transform=r.get("modify_transform"),
        )
        for r in data.get("rules", [])
    ]

    dc = data.get("data_classification", {})

    def _frozenset_or_none(lst: list | None) -> "frozenset[str] | None":
        return frozenset(lst) if lst else None

    return Policy(
        denied_tools=set(data.get("denied_tools", [])),
        required_params={k: list(v) for k, v in data.get("required_params", {}).items()},
        max_actions=int(data.get("max_actions", 50)),
        rules=rules,
        pii_keywords=_frozenset_or_none(dc.get("pii_keywords")),
        confidential_keywords=_frozenset_or_none(dc.get("confidential_keywords")),
        sensitive_tools=_frozenset_or_none(dc.get("sensitive_tools")),
        destructive_tools=_frozenset_or_none(dc.get("destructive_tools")),
    )
