import asyncio
import json

PARENT = '55576e95-bb81-40c3-b999-e4852493b39e'

async def main():
    import asyncpg
    conn = await asyncpg.connect('postgresql://parthenon:parthenon@localhost:5432/parthenon')

    rows = await conn.fetch('''
        SELECT event_type, message, timestamp, data
        FROM execution_log_entries
        WHERE session_id = $1
        ORDER BY timestamp
    ''', PARENT)

    print(f'Total events for {PARENT[:8]}: {len(rows)}')
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
        print(f'{ts} {evt:30} {msg}')
        if evt == 'tool_response' and 'response_preview' in d:
            print(f'         RESPONSE -> {str(d["response_preview"])[:300]}')
        if evt == 'llm_response':
            usage = d.get('usage', {})
            print(f'         tokens={usage}')
        if evt == 'tool_call':
            print(f'         args={str(d.get("args", d))[:150]}')

    await conn.close()

asyncio.run(main())
