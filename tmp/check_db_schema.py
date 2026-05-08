"""Quick DB schema check for migration planning."""
import asyncio
from app.db.session import AsyncSessionLocal as async_session_factory
from sqlalchemy import text


async def check():
    async with async_session_factory() as db:
        r = await db.execute(text(
            "SELECT conname FROM pg_constraint WHERE conname IN ('uq_agent_role_skill', 'uq_agent_role_sop')"
        ))
        print("Constraints:", [row[0] for row in r.fetchall()])

        r2 = await db.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='mcp_sessions' AND column_name LIKE 'oauth%'"
        ))
        print("mcp oauth cols:", [row[0] for row in r2.fetchall()])

        r3 = await db.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='agent_types' AND column_name IN ('llm_provider','model_config_id','model_name')"
        ))
        print("agent_types cols:", [row[0] for row in r3.fetchall()])

        r4 = await db.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_name='model_configs'"
        ))
        print("model_configs table:", [row[0] for row in r4.fetchall()])

        r5 = await db.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name='agent_jobs' AND column_name='conversation_history'"
        ))
        print("agent_jobs.conversation_history:", [row[0] for row in r5.fetchall()])


asyncio.run(check())
