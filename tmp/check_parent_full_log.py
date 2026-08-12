import asyncio
import json

async def main():
    import asyncpg
    conn = await asyncpg.connect('postgresql://parthenon:parthenon@localhost:5432/parthenon')

    # Get full execution log for parent df64f42d - all event types
    rows = await conn.fetch('''
        SELECT event_type, message, timestamp, data
        FROM execution_log_entries
        WHERE session_id = 'df64f42d-a047-4eb1-9a02-8fafe8c27814'
        ORDER BY timestamp
    ''')
    print(f'Total events for df64f42d: {len(rows)}')
    for r in rows:
        d = r['data'] if isinstance(r['data'], dict) else {}
        try:
            if isinstance(r['data'], str):
                d = json.loads(r['data'])
        except Exception:
            pass
        ts = r['timestamp'].strftime('%H:%M:%S')
        evt = r['event_type']
        msg = r['message'][:80]
        print(f'{ts} {evt:28} {msg}')
        # Print key fields
        if evt == 'tool_response' and 'response_preview' in d:
            print(f'  -> {str(d["response_preview"])[:200]}')
        if evt in ('llm_call', 'llm_response', 'agent_decision'):
            for k, v in d.items():
                print(f'  {k}: {str(v)[:100]}')
    await conn.close()

asyncio.run(main())
