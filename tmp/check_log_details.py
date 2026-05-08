"""Check actual log entries in database."""
import asyncio
import json
from app.db.session import get_db
from sqlalchemy import text


async def check():
    async for db in get_db():
        result = await db.execute(
            text(
                """
                SELECT session_id, event_type, message, data, timestamp
                FROM execution_log_entries
                WHERE session_id = '4fbf7c79-9a5d-4a7a-8163-1ba8d44fbd9e'
                ORDER BY timestamp
                """
            )
        )
        rows = result.all()
        print(f"Found {len(rows)} log entries:")
        for row in rows:
            print(f"\n--- {row.event_type} at {row.timestamp} ---")
            print(f"Message: {row.message}")
            if row.data:
                print(f"Data: {json.dumps(row.data, indent=2)}")
        await db.close()
        break


if __name__ == "__main__":
    asyncio.run(check())
