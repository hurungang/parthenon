"""Certificate Authority bootstrapping setup.

Ports the CA bootstrapping from ``_initialize_certificate_authority()``
in Control Center startup into an idempotent setup sub-command.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("setup.certificates")


async def run_certificates_setup(args: Any) -> int:
    """Bootstrap the certificate authority.

    Idempotent — loads existing CA certificate from disk or env if present.
    """
    settings = get_settings()
    report: list[dict[str, str]] = []

    # ── Initialize CA ───────────────────────────────────────────────────
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.certificate_authority import initialize_ca
        async with AsyncSessionLocal() as db:
            ca_cert = await initialize_ca(db)

        report.append(_r(
            "ca_initialized",
            "ok",
            f"CA ready — serial={ca_cert.serial_number}, expires={ca_cert.not_valid_after_utc.isoformat()}",
        ))

        # Check if CA was loaded from disk (existing) or generated new
        import os
        _ca_dir = os.path.join(os.path.dirname(__file__), "..", "backend", "certs", "control-center")
        ca_cert_path = os.path.join(os.path.dirname(__file__), "..", "backend", "certs", "control-center", "ca-cert.pem")
        if os.path.exists(ca_cert_path):
            report.append(_r("ca_persistence", "exists", f"CA cert on disk at backend/certs/control-center/"))
        else:
            report.append(_r("ca_persistence", "created", "CA generated and persisted to disk"))
    except Exception as exc:
        logger.exception("CA bootstrapping failed")
        report.append(_r("ca_initialized", "error", str(exc)))
        return _output(args, report, failed=True)

    return _output(args, report)


def _output(args: Any, report: list[dict[str, str]], failed: bool = False) -> int:
    if args.output == "json":
        print(json.dumps({"status": "error" if failed else "ok", "steps": report}, indent=2))
    else:
        for r in report:
            icon = "✗" if r["status"] == "error" else "✓"
            print(f"  {icon} {r['step']}: {r['detail']}")
    return 1 if failed or any(r["status"] == "error" for r in report) else 0


def _r(step: str, status: str, detail: str = "") -> dict[str, str]:
    return {"step": step, "status": status, "detail": detail}
