import asyncio
import json

async def main():
    import asyncpg
    conn = await asyncpg.connect('postgresql://parthenon:parthenon@localhost:5432/parthenon')
    rows = await conn.fetch('''
        SELECT event_type, message, timestamp, data
        FROM execution_log_entries
        WHERE session_id = 'df64f42d-a047-4eb1-9a02-8fafe8c27814'
          AND event_type IN (
            'delegation_started','delegation_waiting','delegation_resumed',
            'tool_response','delegation_failed','task_loop_completed'
          )
        ORDER BY timestamp
    ''')
    print(f'Found {len(rows)} rows for df64f42d')
    for r in rows:
        d = r['data'] if isinstance(r['data'], dict) else {}
        try:
            if isinstance(r['data'], str):
                d = json.loads(r['data'])
        except Exception:
            pass
        ts = r['timestamp'].strftime('%H:%M:%S')
        evt = r['event_type']
        msg = r['message'][:70]
        print(f'{ts} {evt:25} {msg}')
        if 'response_preview' in d:
            print(f'  response: {str(d["response_preview"])[:150]}')
    await conn.close()

asyncio.run(main())
