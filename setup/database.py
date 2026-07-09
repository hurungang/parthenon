"""Database seeding setup — system roles, permissions, skills, system tools.

Ports the database initialization logic from ``scripts/init-local-dev.py``
and Control Center bootstrap services into an idempotent setup sub-command.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.models.identity import Role
from app.db.models.platform_user import PlatformUser
from app.db.models.user_role import UserRole
from app.db.models.policy_statement import PolicyStatement, PolicyEffect
from app.db.models.policy_action import PolicyAction
from app.db.models.policy_resource import PolicyResource

logger = logging.getLogger("setup.database")


async def run_database_setup(args: Any) -> int:
    """Verify database readiness and seed system data."""
    settings = get_settings()
    report: list[dict[str, str]] = []

    # ── Verify database reachability ───────────────────────────────────
    engine = create_async_engine(str(settings.database_url))
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with async_session() as db:
            await db.execute(select(Role).where(Role.name == "system_admin").limit(0))
        report.append(_r("db_reachable", "ok", "Database is reachable"))
    except Exception as exc:
        report.append(_r("db_reachable", "error", str(exc)))
        await engine.dispose()
        return _output(args, report, failed=True)

    # ── Seed system_admin role ─────────────────────────────────────────
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Role).where(Role.name == "system_admin", Role.is_system.is_(True))
            )
            role = result.scalar_one_or_none()

            if role:
                report.append(_r("system_admin_role", "exists", f"Role ID: {role.id}"))
            else:
                role = Role(
                    name="system_admin",
                    description="System administrator — full platform access. Immutable.",
                    is_system=True,
                    is_active=True,
                )
                db.add(role)
                await db.flush()

                # Wildcard policy
                stmt = PolicyStatement(
                    role_id=role.id,
                    effect=PolicyEffect.allow,
                    module="*::*",
                )
                db.add(stmt)
                await db.flush()

                db.add(PolicyAction(policy_statement_id=stmt.id, action="*"))
                db.add(PolicyResource(policy_statement_id=stmt.id, resource_type="*::*", resource_id="*"))
                await db.flush()

                report.append(_r("system_admin_role", "created", f"Role ID: {role.id}"))
                report.append(_r("wildcard_policy", "created", f"Policy ID: {stmt.id}"))

            await db.commit()

            # ── Assign role to admin user if specified ─────────────────
            admin_email = args.admin_email or os.environ.get("BOOTSTRAP_ADMIN_EMAIL", "").strip()
            if admin_email:
                user_result = await db.execute(
                    select(PlatformUser).where(PlatformUser.email == admin_email)
                )
                user = user_result.scalar_one_or_none()
                if user:
                    existing = await db.execute(
                        select(UserRole).where(
                            UserRole.user_id == user.id,
                            UserRole.role_id == role.id,
                        )
                    )
                    if existing.scalar_one_or_none():
                        report.append(_r("admin_role", "exists", f"User {admin_email} already has system_admin"))
                    else:
                        db.add(UserRole(user_id=user.id, role_id=role.id))
                        await db.commit()
                        report.append(_r("admin_role", "created", f"Assigned system_admin to {admin_email}"))
                else:
                    report.append(_r("admin_role", "skipped", f"User {admin_email} not found in platform_users"))
    except Exception as exc:
        logger.exception("Database seeding failed")
        report.append(_r("database_seed", "error", str(exc)))
        await engine.dispose()
        return _output(args, report, failed=True)

    # ── Seed skills ─────────────────────────────────────────────────────
    try:
        from app.services.skill_seeder import SkillSeeder
        async with async_session() as db:
            summary = await SkillSeeder().run(db)
            await db.commit()
        for skill_name, action in summary.items():
            report.append(_r(f"skill:{skill_name}", action, ""))
    except Exception as exc:
        logger.exception("Skill seeding failed")
        report.append(_r("skill_seed", "error", str(exc)))

    # ── Seed system tools ───────────────────────────────────────────────
    try:
        from app.db.session import AsyncSessionLocal as CCAsyncSessionLocal
        from app.api.v1.mcp_hub import seed_system_tools
        async with CCAsyncSessionLocal() as db:
            await seed_system_tools(db)
            await db.commit()
        report.append(_r("system_tools", "created", "System tools seeded"))
    except Exception as exc:
        logger.exception("System tools seeding failed")
        report.append(_r("system_tools", "error", str(exc)))

    await engine.dispose()
    return _output(args, report)


def _output(args: Any, report: list[dict[str, str]], failed: bool = False) -> int:
    if args.output == "json":
        print(json.dumps({"status": "error" if failed else "ok", "steps": report}, indent=2))
    else:
        for r in report:
            if r["status"] == "ok":
                print(f"  ✓ {r['step']}: {r['detail']}")
            elif r["status"] == "error":
                print(f"  ✗ {r['step']}: {r['detail']}")
            elif r["status"] in ("exists", "skipped"):
                print(f"  ● {r['step']}: {r['status']} ({r['detail']})" if r.get("detail") else f"  ● {r['step']}: {r['status']}")
            else:
                print(f"  ✓ {r['step']}: {r['status']} {r.get('detail', '')}")
    return 1 if failed or any(r["status"] == "error" for r in report) else 0


def _r(step: str, status: str, detail: str = "") -> dict[str, str]:
    return {"step": step, "status": status, "detail": detail}
