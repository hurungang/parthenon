"""Check agent identity configuration."""
import asyncio
from app.db.session import get_db
from app.db.models.agents import AgentType, AgentIdentity
from sqlalchemy import select

async def check():
    async for db in get_db():
        # Get agent types
        result = await db.execute(select(AgentType.id, AgentType.name, AgentType.identity_id))
        types = result.all()
        
        print("Agent Types:")
        for t in types:
            print(f"  {t.name} (id={t.id}): identity_id={t.identity_id}")
        
        # Check first agent type's identity
        if types and types[0].identity_id:
            result2 = await db.execute(select(AgentIdentity).where(AgentIdentity.id == types[0].identity_id))
            identity = result2.scalar_one_or_none()
            
            if identity:
                print(f"\nAgent Identity '{identity.name}':")
                print(f"  access_token: {'SET' if identity.access_token else 'NULL'}")
                print(f"  refresh_token (OLD): {'SET' if identity.refresh_token else 'NULL'}")
                print(f"  encrypted_refresh_token (NEW): {'SET' if identity.encrypted_refresh_token else 'NULL'}")
                print(f"  token_expires_at: {identity.token_expires_at}")
                print(f"  token_status: {identity.token_status}")
        break

asyncio.run(check())
