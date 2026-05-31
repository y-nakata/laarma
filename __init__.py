"""AARM root package.

このパッケージは `aarm/sdk/src/aarm` の SDK 実装を同じ名前空間にマージし、
`aarm.agent` / `aarm.platform` を同一ルートから読み込めるようにします。
"""

from pathlib import Path

# SDK ソースを同じ aarm パッケージに追加する
__path__.append(str(Path(__file__).resolve().parent / "sdk" / "src" / "aarm"))

from .context_accumulator import ContextAccumulator
from .models import Action, AuthorizationResult, Decision, IdentityContext, SessionContext
from .policy_engine import DEFAULT_POLICY, Policy, PolicyEngine
from .runtime import AARMRuntime
from .tool_proxy import AARMToolProxy, ToolBlocked

__all__ = [
    "AARMRuntime",
    "AARMToolProxy",
    "ToolBlocked",
    "Action",
    "AuthorizationResult",
    "Decision",
    "IdentityContext",
    "SessionContext",
    "ContextAccumulator",
    "DEFAULT_POLICY",
    "Policy",
    "PolicyEngine",
]
