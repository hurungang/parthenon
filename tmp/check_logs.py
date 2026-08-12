"""Quick script to check execution log entries."""
import asyncio
from app.db.session import get_db
from sqlalchemy import text


async def check():
    async for db in get_db():
        result = await db.execute(
            text(
                """
                SELECT session_id, event_type, COUNT(*) as count 
                FROM execution_log_entries 
                GROUP BY session_id, event_type 
                ORDER BY session_id
                """
            )
        )
        rows = result.all()
        if rows:
            print("Execution log entries:")
            for row in rows:
                print(f"  Session {row[0]}: {row[1]} ({row[2]} entries)")
        else:
            print("No execution log entries found")
        await db.close()
        break


if __name__ == "__main__":
    asyncio.run(check())
