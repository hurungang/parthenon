"""Create a demo AgentClient (secret) for local testing of the integration gateway.

Run from the backend directory:

    cd backend
    ../.venv/bin/python ../scripts/create-demo-agent-client.py [agent_type_id]

Prints a `phn_cl_sk_…` secret you can paste into the Agent Client demo app.
This bypasses the admin API for convenience — use the UI for real client creation.
"""
from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import select

from app.db.models.agent_client import (
    AgentClient,
    AgentClientKeyType,
    AgentClientStatus,
)
from app.db.models.agents import AgentInputType, AgentType
from app.db.models.tenant import Tenant
from app.db.session import AsyncSessionLocal
from app.services.agent_client_service import generate_client_key, slugify


async def main() -> int:
    async with AsyncSessionLocal() as db:
        agent_type: AgentType | None = None
        if len(sys.argv) > 1:
            agent_type = await db.get(AgentType, uuid.UUID(sys.argv[1]))
        else:
            root = (
                await db.execute(select(Tenant).where(Tenant.is_system_tenant.is_(True)))
            ).scalar_one_or_none()
            stmt = select(AgentType).where(AgentType.is_active.is_(True))
            if root is not None:
                stmt = stmt.where(AgentType.tenant_id == root.id)
            types = (await db.execute(stmt)).scalars().all()
            if not types and root is not None:
                # Fall back to any active agent type if the root tenant has none.
                types = (
                    await db.execute(
                        select(AgentType).where(AgentType.is_active.is_(True))
                    )
                ).scalars().all()
            conv = [t for t in types if t.input_type == AgentInputType.conversation]
            agent_type = (conv or types)[0] if (conv or types) else None

        if agent_type is None:
            print("No active agent type found. Pass an agent_type_id as the first argument.")
            return 1

        raw, key_hash, prefix = generate_client_key(AgentClientKeyType.secret)
        suffix = uuid.uuid4().hex[:8]
        client = AgentClient(
            tenant_id=agent_type.tenant_id,
            name=f"demo-{suffix}",
            slug=slugify(f"demo-{suffix}"),
            agent_type_id=agent_type.id,
            key_type=AgentClientKeyType.secret,
            key_hash=key_hash,
            key_prefix=prefix,
            status=AgentClientStatus.active,
        )
        db.add(client)
        await db.commit()
        await db.refresh(client)

        print("agent_type :", agent_type.id, "|", agent_type.name, "|", agent_type.input_type.value)
        print("tenant_id  :", agent_type.tenant_id)
        print("client_id  :", client.id)
        print("")
        print("CLIENT_SECRET:", raw)
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
