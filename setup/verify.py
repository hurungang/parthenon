"""Verify — read-only check of current environment state.

Reports what is and is not configured without making any changes.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models.identity import Role

logger = logging.getLogger("setup.verify")


async def run_verify(args: Any) -> int:
    """Check current state of all components without making changes."""
    settings = get_settings()
    report: list[dict[str, str]] = []

    # ── Identity Provider ────────────────────────────────────────────────
    report.append(_r(
        "identity_provider",
        "configured" if settings.identity_setup_complete else "not_configured",
        f"provider_type={settings.identity_provider_type or 'unconfigured'}, "
        f"realm={settings.identity_realm or 'unset'}",
    ))

    # ── Database reachability ───────────────────────────────────────────
    try:
        engine = create_async_engine(str(settings.database_url))
        async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as db:
            result = await db.execute(
                select(Role).where(Role.name == "system_admin", Role.is_system.is_(True))
            )
            role = result.scalar_one_or_none()
        report.append(_r(
            "database",
            "reachable",
            f"system_admin role: {'exists' if role else 'missing'}",
        ))
        await engine.dispose()
    except Exception as exc:
        report.append(_r("database", "unreachable", str(exc)))

    # ── OIDC provider ───────────────────────────────────────────────────
    import httpx
    discovery_url = f"{settings.oidc_provider_url.rstrip('/')}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(discovery_url)
        if resp.status_code == 200:
            report.append(_r("oidc_provider", "reachable", discovery_url))
        else:
            report.append(_r("oidc_provider", f"HTTP {resp.status_code}", discovery_url))
    except Exception as exc:
        report.append(_r("oidc_provider", "unreachable", str(exc)))

    # ── Redis ───────────────────────────────────────────────────────────
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        await client.ping()
        await client.aclose()
        report.append(_r("redis", "reachable", settings.redis_url))
    except Exception as exc:
        report.append(_r("redis", "unreachable", str(exc)))

    # ── CA ──────────────────────────────────────────────────────────────
    import os
    _ca_path = os.path.join(
        os.path.dirname(__file__), "..", "backend", "certs", "control-center", "ca-cert.pem"
    )
    if os.path.exists(_ca_path):
        report.append(_r("certificate_authority", "exists", _ca_path))
    else:
        report.append(_r("certificate_authority", "not_found", "CA cert not on disk — will generate on startup"))

    # ── Output ──────────────────────────────────────────────────────────
    if args.output == "json":
        print(json.dumps({"status": "ok", "checks": report}, indent=2))
    else:
        print("Environment State:")
        for r in report:
            icon = "✓" if r["status"] in ("reachable", "exists", "configured") else "✗"
            print(f"  {icon} {r['step']}: {r['status']} — {r.get('detail', '')}")

    return 0


def _r(step: str, status: str, detail: str = "") -> dict[str, str]:
    return {"step": step, "status": status, "detail": detail}
