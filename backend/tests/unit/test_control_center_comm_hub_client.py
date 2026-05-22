from __future__ import annotations

import pytest

from unittest.mock import patch

from app.services.control_center.comm_hub_client import (
    CommunicationHubClient,
    CommunicationHubClientError,
)


def test_make_client_http_uses_client_certificate_header(tmp_path) -> None:
    cert_path = tmp_path / "service-cert.pem"
    key_path = tmp_path / "service-key.pem"

    cert_path.write_text(
        "-----BEGIN CERTIFICATE-----\nabc\n-----END CERTIFICATE-----\n",
        encoding="utf-8",
    )
    key_path.write_text("dummy-key", encoding="utf-8")

    with patch("app.services.control_center.comm_hub_client.httpx.AsyncClient") as mock_client:
        client = CommunicationHubClient(
            comm_hub_url="http://localhost:8002",
            cert_path=str(cert_path),
            key_path=str(key_path),
        )

        client._make_client()

    kwargs = mock_client.call_args.kwargs
    assert kwargs["verify"] is False
    assert "headers" in kwargs
    assert "X-Client-Certificate" in kwargs["headers"]
    assert "\\n" in kwargs["headers"]["X-Client-Certificate"]


def test_init_uses_default_cc_cert_paths_when_env_missing() -> None:
    with patch.dict(
        "app.services.control_center.comm_hub_client.os.environ",
        {"COMM_HUB_URL": "http://localhost:8002"},
        clear=True,
    ):
        client = CommunicationHubClient()

    assert client._cert_path == "certs/control-center/service-cert.pem"
    assert client._key_path == "certs/control-center/service-key.pem"


def test_make_client_without_cert_fails_closed_outside_dev_opt_in() -> None:
    client = CommunicationHubClient(
        comm_hub_url="http://localhost:8002",
        cert_path="does/not/exist/service-cert.pem",
        key_path="does/not/exist/service-key.pem",
    )

    with patch.dict(
        "app.services.control_center.comm_hub_client.os.environ",
        {"ENVIRONMENT": "test"},
        clear=True,
    ):
        with pytest.raises(CommunicationHubClientError):
            client._make_client()
