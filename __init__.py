"""AARM root package.

This package merges the local AARM SDK implementation from `aarm/sdk/src/aarm`
into the root package namespace.
"""

from pathlib import Path

# SDK ソースを同じ aarm パッケージに追加する
__path__.append(str(Path(__file__).resolve().parent / "sdk" / "src" / "aarm"))

from .models import IdentityContext

__all__ = ["IdentityContext"]
