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
