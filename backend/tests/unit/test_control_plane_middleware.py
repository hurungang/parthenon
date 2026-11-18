"""Unit tests for ControlPlaneMiddleware expected-service route mapping."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.communication_hub.middleware.control_plane import ControlPlaneMiddleware


async def _call_next(_request):
    return SimpleNamespace(status_code=200)


@pytest.mark.asyncio
async def test_a2a_request_uses_agent_runtime_expected_service() -> None:
    middleware = ControlPlaneMiddleware(app=MagicMock())

    mock_request = MagicMock()
    mock_request.method = "POST"
    mock_request.url.path = "/internal/a2a/request"
    mock_request.headers = {"X-Client-Certificate": "dummy-cert"}
    mock_request.state = MagicMock()

    with patch(
        "app.communication_hub.middleware.control_plane._load_ca_cert_pem",
        return_value="dummy-ca",
    ), patch(
        "app.communication_hub.middleware.control_plane._get_control_center_url",
        return_value="",
    ), patch(
        "app.communication_hub.middleware.control_plane.validate_service_cert_locally",
        return_value=SimpleNamespace(
            valid=True, reason=None, service_name="agent-runtime", serial_number="123"
        ),
    ) as validate_mock:
        response = await middleware.dispatch(mock_request, _call_next)

    assert response.status_code == 200
    assert validate_mock.call_args.kwargs["expected_service_name"] == "agent-runtime"


@pytest.mark.asyncio
async def test_true_control_plane_route_uses_control_center_expected_service() -> None:
    middleware = ControlPlaneMiddleware(app=MagicMock())

    mock_request = MagicMock()
    mock_request.method = "POST"
    mock_request.url.path = "/internal/dispatch"
    mock_request.headers = {"X-Client-Certificate": "dummy-cert"}
    mock_request.state = MagicMock()

    with patch(
        "app.communication_hub.middleware.control_plane._load_ca_cert_pem",
        return_value="dummy-ca",
    ), patch(
        "app.communication_hub.middleware.control_plane._get_control_center_url",
        return_value="",
    ), patch(
        "app.communication_hub.middleware.control_plane.validate_service_cert_locally",
        return_value=SimpleNamespace(
            valid=True,
            reason=None,
            service_name="control-center",
            serial_number="456",
        ),
    ) as validate_mock:
        response = await middleware.dispatch(mock_request, _call_next)

    assert response.status_code == 200
    assert validate_mock.call_args.kwargs["expected_service_name"] == "control-center"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/internal/checkpoint/11111111-1111-1111-1111-111111111111",
        "/internal/turn-resume/11111111-1111-1111-1111-111111111111",
        "/internal/turn-resume/11111111-1111-1111-1111-111111111111/claim",
        "/internal/turn-resume/11111111-1111-1111-1111-111111111111/complete",
    ],
)
async def test_agent_runtime_relay_paths_accept_agent_runtime_cert(path: str) -> None:
    """AR's checkpoint / resume-index relay routes accept AR certificates.

    Agent Runtime holds no Control Center path, so these CH routes are its
    courier surface; they must be validated as agent-runtime traffic (and stay
    transport-only).
    """
    middleware = ControlPlaneMiddleware(app=MagicMock())

    mock_request = MagicMock()
    mock_request.method = "PUT"
    mock_request.url.path = path
    mock_request.headers = {"X-Client-Certificate": "dummy-cert"}
    mock_request.state = MagicMock()

    with patch(
        "app.communication_hub.middleware.control_plane._load_ca_cert_pem",
        return_value="dummy-ca",
    ), patch(
        "app.communication_hub.middleware.control_plane._get_control_center_url",
        return_value="",
    ), patch(
        "app.communication_hub.middleware.control_plane.validate_service_cert_locally",
        return_value=SimpleNamespace(
            valid=True, reason=None, service_name="agent-runtime", serial_number="999"
        ),
    ) as validate_mock:
        response = await middleware.dispatch(mock_request, _call_next)

    assert response.status_code == 200
    assert validate_mock.call_args.kwargs["expected_service_name"] == "agent-runtime"


@pytest.mark.asyncio
async def test_agent_execute_path_requires_control_center_cert() -> None:
    """``/internal/agent/execute`` is validated like any control-plane path.

    Control Center carries its own service certificate
    (``service:control-center``), so the execute path must no longer be
    exempt from cert validation (FIX: removed the cert-exempt bypass).
    """
    middleware = ControlPlaneMiddleware(app=MagicMock())

    mock_request = MagicMock()
    mock_request.method = "POST"
    mock_request.url.path = "/internal/agent/execute"
    mock_request.headers = {"X-Client-Certificate": "dummy-cert"}
    mock_request.state = MagicMock()

    with patch(
        "app.communication_hub.middleware.control_plane._load_ca_cert_pem",
        return_value="dummy-ca",
    ), patch(
        "app.communication_hub.middleware.control_plane._get_control_center_url",
        return_value="",
    ), patch(
        "app.communication_hub.middleware.control_plane.validate_service_cert_locally",
        return_value=SimpleNamespace(
            valid=True,
            reason=None,
            service_name="control-center",
            serial_number="789",
        ),
    ) as validate_mock:
        response = await middleware.dispatch(mock_request, _call_next)

    assert response.status_code == 200
    assert validate_mock.call_args.kwargs["expected_service_name"] == "control-center"
