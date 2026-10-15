"""Isolated repository execution infrastructure.

The package deliberately has no dependency on FastAPI or application business
logic.  Consumers opt in by constructing :class:`SandboxManager`.
"""

from .executor import CommandResult, SandboxRunResult
from .manager import SandboxConfig, SandboxManager, SandboxSession

__all__ = [
    "CommandResult",
    "SandboxConfig",
    "SandboxManager",
    "SandboxRunResult",
    "SandboxSession",
]
