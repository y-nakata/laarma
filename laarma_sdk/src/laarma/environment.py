"""
AARM 環境コンテキスト (E) — 仕様 IV-A2

仕様の形式モデルにおける E (環境) を表現する。
データストア・ API ・クラウドサービスの稿働状態、メンテナンス窓、環境種別などを保持する。

IntentAlignment は環境コンテキストを考慮して DEFER / STEP_UP を判断する。
例: "定期メンテナンス窓外での認証情報ローテーション"→ E にメンテナンス窓がなければ DEFER。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MaintenanceWindow:
    """定期メンテナンス窓の定義。"""
    name:       str
    start_hour: int   # UTC
    end_hour:   int   # UTC
    days:       list[str] = field(default_factory=lambda: ["Mon", "Tue", "Wed", "Thu", "Fri"])

    def is_active(self, dt: datetime | None = None) -> bool:
        dt = dt or datetime.now(timezone.utc)
        day_name = dt.strftime("%a")
        return day_name in self.days and self.start_hour <= dt.hour < self.end_hour


@dataclass
class EnvironmentContext:
    """
    環境コンテキスト E — 仕様 IV-A2。

    Attributes:
        environment:          環境種別 ("production" | "staging" | "development" | ...)
        maintenance_windows:  定期メンテナンス窓の一覧
        high_sensitivity:     True の場合、骸尲性の高い環境（教師側のリスク初期化を促進）
        custom:               実装依存の任意フィールド
    """
    environment:         str                     = "production"
    maintenance_windows: list[MaintenanceWindow] = field(default_factory=list)
    high_sensitivity:    bool                    = False
    custom:              dict[str, Any]          = field(default_factory=dict)

    def in_maintenance_window(self, dt: datetime | None = None) -> bool:
        """現在時刻がいずれかのメンテナンス窓内かどうか。"""
        return any(w.is_active(dt) for w in self.maintenance_windows)

    def to_dict(self) -> dict:
        dt = datetime.now(timezone.utc)
        return {
            "environment":            self.environment,
            "in_maintenance_window":  self.in_maintenance_window(dt),
            "maintenance_windows":    [
                {
                    "name":     w.name,
                    "active":   w.is_active(dt),
                    "schedule": f"{w.start_hour:02d}:00-{w.end_hour:02d}:00 UTC {', '.join(w.days)}",
                }
                for w in self.maintenance_windows
            ],
            "high_sensitivity":       self.high_sensitivity,
            "custom":                 self.custom,
        }
