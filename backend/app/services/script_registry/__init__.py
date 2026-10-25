"""Script Registry service package (Control Center governance plane).

The only code path in the platform that reads/writes the Software 3.0
script tables. Agent Runtime interacts exclusively through the CC
internal API (`/api/v1/internal/scripts/...`).
"""
from app.services.script_registry.service import ScriptRegistryService, LifecycleTransitionError

__all__ = [
    "ScriptRegistryService",
    "LifecycleTransitionError",
]
