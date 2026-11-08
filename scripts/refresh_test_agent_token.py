"""One-off: refresh the expired OAuth token for an agent identity by realm username.

Usage: .venv/bin/python scripts/refresh_test_agent_token.py [realm_username]
Defaults to 'test_agent@ai_agents'.
"""
import asyncio
import sys

sys.path.insert(0, ".")


async def main() -> None:
    realm_username = sys.argv[1] if len(sys.argv) > 1 else "test_agent@ai_agents"
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models.agents import AgentIdentity
    from app.services.agents.identity_service import AgentIdentityService

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(AgentIdentity)
            .where(AgentIdentity.realm_username == realm_username)
            .order_by(AgentIdentity.token_expires_at.desc().nulls_last())
            .limit(1)
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            print(f"NOT FOUND: no AgentIdentity with realm_username={realm_username!r}")
            return
        print(f"Found identity {identity.id} name={identity.name!r} "
              f"expires_at={identity.token_expires_at} "
              f"last_refresh={identity.last_token_refresh_at} "
              f"outcome={identity.last_token_refresh_outcome}")
        svc = AgentIdentityService()
        try:
            refreshed = await svc.refresh_token(identity_id=identity.id, db=db)
            await db.commit()
            print(f"OK: token refreshed, new expires_at={refreshed.token_expires_at}")
        except Exception as exc:
            await db.rollback()
            print(f"REFRESH FAILED: {type(exc).__name__}: {exc}")
            raise SystemExit(1)


asyncio.run(main())
