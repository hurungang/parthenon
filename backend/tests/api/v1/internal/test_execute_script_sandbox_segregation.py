"""Segregation guard: CC NEVER executes the sandbox (source scan).

Top-priority rule: sandboxed scripts execute ONLY in Agent Runtime — the CC
process keeps no sandbox execution path. Historically ``execute_script``
imported ``run_sandboxed_python`` from ``app.agent_runtime.scripts.sandbox``
and ran the sandbox INSIDE Control Center (also losing the session-bound
tool client — ``tools.call`` was ``None`` → ``TypeError: 'NoneType' object
is not callable``). This scan pins the fix: the CC optimization-tools module
routes verification through the CC→CH→AR internal-call mechanism and never
touches the sandbox modules (mirrors the AR/CH egress-scan test style).
"""
from __future__ import annotations

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[4]
TARGET = BACKEND_ROOT / "app/api/v1/internal/optimization_tools.py"


def _source() -> str:
    return TARGET.read_text()


def test_cc_optimization_tools_never_import_or_call_the_sandbox():
    """No ``run_sandboxed_python`` / sandbox-module import in the CC handler."""
    source = _source()
    assert "run_sandboxed_python" not in source, (
        "ARCHITECTURE VIOLATION: CC optimization_tools executes the sandbox "
        "directly — scripts may execute ONLY in Agent Runtime. Route "
        "verification through CommunicationHubClient.forward_sandboxed_script."
    )
    assert "scripts.sandbox" not in source
    assert "SandboxCaps" not in source


def test_cc_execute_script_routes_through_the_comm_hub_client():
    """The verification primitive goes through the CC→CH→AR client seam."""
    source = _source()
    assert "CommunicationHubClient" in source
    assert "forward_sandboxed_script" in source


def test_cc_execute_script_never_targets_the_ar_cert_only_tool_call_path():
    """CC must NOT call CH ``/internal/tools/call`` — ControlPlaneMiddleware
    only accepts AGENT-RUNTIME certificates on ``/internal/tools/``, so the
    CC-cert hop there is architecturally rejected. The dedicated CC-cert hop
    is CH ``/internal/script-tools/forward`` (CH then forwards to AR with
    CH's own cert, identical to the ``script____<name>`` route)."""
    source = _source()
    assert "/internal/tools/call" not in source
    assert "script____inline" not in source
