"""FIX-20261031-131030 (defect 1) — CWD-independent certificate path resolution.

A service restarted from the wrong working directory used to resolve relative
``certs/...`` paths against the process CWD, silently pointing at
non-existent files — the failure surfaced lazily at first use
(``FileNotFoundError: 'certs/communication-hub-cert.pem'`` at LLM-call time)
while health probes stayed green.

These tests pin:

- relative cert paths resolve to the backend-root-anchored location
  regardless of the process working directory (exercised under ``os.chdir``);
- absolute paths (explicit ``*_CERT_PATH``-style config) pass through;
- CH/AR certificate managers and the CC service-cert renewal default anchor
  to the backend root;
- startup validation fails fast with a clear message when a resolved cert
  file is missing.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.core.cert_paths import (
    BACKEND_ROOT,
    CertValidationError,
    ensure_cert_files_exist,
    resolve_cert_path,
)


# ── Resolution is CWD-independent ────────────────────────────────────────────


def test_relative_path_anchors_to_backend_root_regardless_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run the resolution under a totally different CWD — the result must
    still be anchored to the backend root, not the (wrong) CWD."""
    monkeypatch.chdir(tmp_path)
    resolved = resolve_cert_path("certs/communication-hub-cert.pem")
    assert resolved is not None
    assert resolved.is_absolute()
    assert resolved == BACKEND_ROOT / "certs" / "communication-hub-cert.pem"
    assert tmp_path not in resolved.parents or resolved == (
        tmp_path / "certs" / "communication-hub-cert.pem"
    ) is False


def test_resolution_matches_real_cert_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for relative in (
        "certs/communication-hub-cert.pem",
        "certs/agent-runtime-cert.pem",
        "certs/ca-cert.pem",
        "certs/control-center/service-cert.pem",
    ):
        resolved = resolve_cert_path(relative)
        assert resolved == BACKEND_ROOT / relative


def test_absolute_path_passes_through(tmp_path: Path) -> None:
    absolute = tmp_path / "my-cert.pem"
    assert resolve_cert_path(str(absolute)) == absolute
    assert resolve_cert_path(absolute) == absolute


def test_none_resolves_to_none() -> None:
    assert resolve_cert_path(None) is None


def test_backend_root_is_backend_directory() -> None:
    assert BACKEND_ROOT.name == "backend"
    assert (BACKEND_ROOT / "app").is_dir()


# ── Service components use the anchored resolution ───────────────────────────


def test_ch_certificate_manager_resolves_relative_env_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even started from a wrong CWD, the CH manager stores backend-root-anchored paths."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COMM_HUB_CERT_PATH", "certs/communication-hub-cert.pem")
    monkeypatch.setenv("COMM_HUB_KEY_PATH", "certs/communication-hub-key.pem")
    monkeypatch.setenv("COMM_HUB_CA_CERT_PATH", "certs/ca-cert.pem")
    monkeypatch.setenv("CONTROL_CENTER_URL", "http://localhost:8000")

    from app.communication_hub.certificate_manager import CommHubCertificateManager

    manager = CommHubCertificateManager()
    # load_certificate validates against CC (or fails if CC is down) — either
    # way the stored paths must be backend-root anchored, never CWD-relative.
    import asyncio

    try:
        asyncio.run(manager.load_certificate())
    except Exception:  # noqa: BLE001 — CC unreachable in unit env is fine
        pass
    assert manager.cert_path == BACKEND_ROOT / "certs" / "communication-hub-cert.pem"
    assert manager.key_path == BACKEND_ROOT / "certs" / "communication-hub-key.pem"


def test_cc_renewal_default_cert_dir_is_anchored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core import cc_service_cert_renewal as renewal

    monkeypatch.chdir(tmp_path)
    assert renewal.DEFAULT_CERT_DIR == BACKEND_ROOT / "certs" / "control-center"
    # Relative explicit dirs also anchor.
    resolved = renewal.renew_cc_service_certificate_if_needed.__doc__  # noqa: F841
    from app.core.cert_paths import resolve_cert_path

    assert resolve_cert_path("certs/control-center") == renewal.DEFAULT_CERT_DIR


def test_cc_outbound_clients_resolve_relative_cert_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CC_CERT_PATH", "certs/control-center/service-cert.pem")
    monkeypatch.setenv("CC_KEY_PATH", "certs/control-center/service-key.pem")

    from app.services.control_center.comm_hub_client import CommunicationHubClient

    client = CommunicationHubClient()
    assert str(client._cert_path) == str(BACKEND_ROOT / "certs/control-center/service-cert.pem")
    assert str(client._key_path) == str(BACKEND_ROOT / "certs/control-center/service-key.pem")


# ── Startup validation fails fast ────────────────────────────────────────────


def test_ensure_cert_files_exist_fails_fast_when_missing(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.pem"
    with pytest.raises(CertValidationError) as excinfo:
        ensure_cert_files_exist([missing])
    assert str(missing) in str(excinfo.value)
    # Actionable guidance is included.
    assert "CERT_PATH" in str(excinfo.value) or "bootstrap" in str(excinfo.value)


def test_ensure_cert_files_exist_passes_when_present(tmp_path: Path) -> None:
    present = tmp_path / "ok.pem"
    present.write_text("-----BEGIN CERTIFICATE-----")
    resolved = ensure_cert_files_exist([present, None])
    assert resolved == [present]


def test_ensure_cert_files_exist_resolves_relative_under_foreign_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real certs live under backend/certs — validation must find them
    from any CWD."""
    monkeypatch.chdir(tmp_path)
    resolved = ensure_cert_files_exist(["certs/ca-cert.pem"])
    assert resolved == [BACKEND_ROOT / "certs" / "ca-cert.pem"]


def test_startup_fail_fast_ch_main_raises_when_cert_unloadable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CH startup certificate load must RAISE (fail fast) instead of the old
    warn-and-continue behavior."""
    import asyncio

    from app.communication_hub import main as ch_main

    monkeypatch.delenv("COMM_HUB_CERT_PATH", raising=False)

    from app.communication_hub.certificate_manager import CertificateLoadError

    async def _fail():
        raise CertificateLoadError("COMM_HUB_CERT_PATH environment variable not set")

    async def _scenario():
        # Simulate manager failure inside _load_certificate by clearing env.
        with pytest.raises(RuntimeError) as excinfo:
            await ch_main._load_certificate()
        return excinfo

    # _load_certificate with COMM_HUB_CERT_PATH unset: manager raises
    # CertificateLoadError; startup must convert it into a fail-fast
    # RuntimeError mentioning the resolved path.
    excinfo = asyncio.run(_scenario())
    assert "startup FAILED" in str(excinfo.value)
    assert "COMM_HUB_CERT_PATH" in str(excinfo.value)
