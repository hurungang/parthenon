"""Integration test fixtures and skip conditions.

Skip conditions are evaluated at test collection time (not import time) to
avoid side effects from external-service availability checks.
"""
import pytest
import os


def _is_service_available(port: int) -> bool:
    """Return True if a TCP service is listening on localhost:port."""
    import socket
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=0.5)
        sock.close()
        return True
    except OSError:
        return False


def _requires_running_services() -> bool:
    """Return True if all required backend services are available."""
    return all(
        _is_service_available(port) for port in (8000, 8001, 8002)
    )


# -- Dynamic skip: service-dependent files --------------------------------------

_SERVICE_DEPENDENT_FILES = {
    "tests/integration/test_nonconv_agent_mcp_tools.py",
    "tests/integration/test_service_triggers.py",
    "tests/integration/test_runtime_control_persistence.py",
    "tests/integration/test_internal_auth_security.py",
    "tests/integration/test_mcp_hub.py",
    "tests/integration/test_mcp_session_identity_lookup.py",
    "tests/integration/test_skill_system_tools.py",
    "tests/integration/test_enhance_mcp_hub_skills_sops_db.py",
    "tests/integration/test_startup_session_cleanup.py",
    "tests/integration/test_agent_execution_with_logs.py",
    "tests/integration/test_system_tool_schemas.py",
    "tests/api/v1/test_model_availability_api.py",
    "tests/api/v1/test_model_usage_guardrails_api.py",
    "tests/api/v1/test_agent_runtime_controls_api.py",
    "tests/api/v1/test_intervene.py",
}


def pytest_collection_modifyitems(config, items):
    skip_services = pytest.mark.skip(reason="Requires running services (CC, AR, or CH)")
    skip_bug = pytest.mark.skip(reason="Pre-existing bug — not from this change")

    for item in items:
        nodeid = item.nodeid
        rel_path = nodeid.split("::")[0]

        # Skip service-dependent files when services are not running
        if rel_path in _SERVICE_DEPENDENT_FILES and not _requires_running_services():
            item.add_marker(skip_services)
