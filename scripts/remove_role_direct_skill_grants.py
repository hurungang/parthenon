"""One-off: remove or restore direct skill grants (AgentRoleSkill rows) for an agent role.

Usage:
  .venv/bin/python scripts/remove_role_direct_skill_grants.py <role_id_or_name> [--dry-run]
      Remove ALL direct skill grants of the role.
  .venv/bin/python scripts/remove_role_direct_skill_grants.py <role_id_or_name> --restore [--dry-run]
      Re-insert grants for the three airline skills looked up by name:
      find-booking-by-pnr, check-in-passenger, create-booking (idempotent).

Resolves the role by UUID or exact name (tenant-scoped to the default tenant
resolution used by the app session), lists the direct grants it would remove,
and deletes them unless --dry-run is given.  After a successful removal it
prints the role's full resolved toolset (via the same permission-resolution
traversal used at runtime) for verification.
"""
import asyncio
import sys

sys.path.insert(0, ".")

RESTORE_SKILL_NAMES = [
    "find-booking-by-pnr",
    "check-in-passenger",
    "create-booking",
]


async def main() -> None:
    restore = "--restore" in sys.argv
    args = [a for a in sys.argv[1:] if a not in ("--dry-run", "--restore")]
    dry_run = "--dry-run" in sys.argv
    if not args:
        print("Usage: python scripts/remove_role_direct_skill_grants.py <role_id_or_name> [--dry-run]")
        raise SystemExit(2)
    role_ref = args[0]

    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models.agents import AgentRole, AgentRoleSkill
    from app.db.models.skills import Skill
    from app.services.permission_resolution import get_allowed_tools

    import uuid as _uuid

    async with AsyncSessionLocal() as db:
        stmt = select(AgentRole)
        if _try_uuid(role_ref):
            stmt = stmt.where(AgentRole.id == _uuid.UUID(role_ref))
        else:
            stmt = stmt.where(AgentRole.name == role_ref)
        role = (await db.execute(stmt)).scalar_one_or_none()
        if role is None:
            print(f"NOT FOUND: no AgentRole matching {role_ref!r}")
            raise SystemExit(1)

        if restore:
            # Restore mode: re-insert grants for the known skills by name
            # (idempotent — existing grants are skipped).
            skills = (
                (
                    await db.execute(
                        select(Skill).where(Skill.name.in_(RESTORE_SKILL_NAMES))
                    )
                )
                .scalars()
                .all()
            )
            found = {s.name: s for s in skills}
            missing = [n for n in RESTORE_SKILL_NAMES if n not in found]
            if missing:
                print(f"WARNING: skills not found (skipped): {', '.join(missing)}")
            existing_ids = set(
                (
                    await db.execute(
                        select(AgentRoleSkill.skill_id).where(
                            AgentRoleSkill.role_id == role.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            to_add = [
                s for s in skills if s.id not in existing_ids
            ]
            if not to_add:
                print(f"Role '{role.name}' ({role.id}) already has all restore grants — nothing to do.")
            else:
                print(f"Restoring direct skill grants for role '{role.name}' ({role.id}):")
                for skill in to_add:
                    print(f"  + {skill.name}")
                if dry_run:
                    print("DRY RUN: nothing restored.")
                else:
                    for skill in to_add:
                        db.add(
                            AgentRoleSkill(
                                role_id=role.id,
                                skill_id=skill.id,
                            )
                        )
                    await db.commit()
                    print(f"RESTORED {len(to_add)} direct skill grant(s).")

        grants = (
            (
                await db.execute(
                    select(AgentRoleSkill, Skill.name)
                    .join(Skill, Skill.id == AgentRoleSkill.skill_id)
                    .where(AgentRoleSkill.role_id == role.id)
                    .order_by(Skill.name)
                )
            ).all()
        )
        if restore:
            # Restore mode never removes; show the final grant state instead.
            grants = (
                (
                    await db.execute(
                        select(AgentRoleSkill, Skill.name)
                        .join(Skill, Skill.id == AgentRoleSkill.skill_id)
                        .where(AgentRoleSkill.role_id == role.id)
                        .order_by(Skill.name)
                    )
                ).all()
            )
            print(f"Role '{role.name}' ({role.id}) current direct skill grants:")
            for _grant, skill_name in grants:
                print(f"  - {skill_name}")
        elif not grants:
            print(f"Role '{role.name}' ({role.id}) has no direct skill grants — nothing to do.")
        else:
            print(f"Role '{role.name}' ({role.id}) direct skill grants:")
            for _grant, skill_name in grants:
                print(f"  - {skill_name}")
            if dry_run:
                print("DRY RUN: nothing removed.")
            else:
                await db.execute(
                    AgentRoleSkill.__table__.delete().where(
                        AgentRoleSkill.role_id == role.id
                    )
                )
                await db.commit()
                print(f"REMOVED {len(grants)} direct skill grant(s).")

        # Verification: resolved toolset via the same runtime traversal.
        tools = await get_allowed_tools(role.id, db)
        print(f"\nResolved toolset for role '{role.name}' ({len(tools)} tools):")
        for tool in sorted(tools):
            print(f"  - {tool}")


def _try_uuid(value: str) -> bool:
    import uuid as _uuid
    try:
        _uuid.UUID(value)
        return True
    except ValueError:
        return False


asyncio.run(main())
