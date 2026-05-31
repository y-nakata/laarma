"""Platform package shim

Expose `run_scenario` from the top-level platform implementation so
`from aarm.platform import run_scenario` continues to work.
"""

# If the interpreter attempts to import the top-level module name `platform`
# (e.g. `import platform`) and this file is picked up as that module, raise
# ImportError so the stdlib `platform` module can be resolved instead. When
# imported as `aarm.platform` the module name will be `aarm.platform` and the
# guard below will not trigger.
if __name__ == "platform":
	raise ImportError("local package 'aarm.platform' should not satisfy top-level import 'platform'.")

from .platform import run_scenario

__all__ = ["run_scenario"]
