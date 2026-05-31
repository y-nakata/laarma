"""AARM root package.

This package merges the local AARM SDK implementation from `aarm/sdk/src/aarm`
into the root package namespace.
"""

from pathlib import Path

# SDK ソースを同じ aarm パッケージに追加する
__path__.append(str(Path(__file__).resolve().parent / "sdk" / "src" / "aarm"))

from .models import IdentityContext

# Ensure the stdlib `platform` module is available under the top-level name
# `platform` so third-party libraries that import `platform` (e.g. the
# Anthropic SDK) don't accidentally resolve a local `aarm.platform` package
# and cause circular import problems.
import importlib, sys
try:
	if 'platform' not in sys.modules:
		sys.modules['platform'] = importlib.import_module('platform')
except Exception:
	# If anything goes wrong, don't fail import of `aarm`; importing stdlib
	# platform is a best-effort attempt to avoid name collisions.
	pass

__all__ = ["IdentityContext"]
