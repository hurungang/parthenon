import asyncio

async def main():
    import asyncpg
    conn = await asyncpg.connect('postgresql://parthenon:parthenon@localhost:5432/parthenon')

    rows = await conn.fetch("""
        SELECT id, parent_job_id, status
        FROM agent_jobs
        WHERE id IN (
          'e8c67375-9eeb-4706-a04e-cc391bdcdd48',
          '6ba2e903-12c1-437d-bf5f-2f936c0b909b',
          '55576e95-bb81-40c3-b999-e4852493b39e'
        )
        ORDER BY created_at
    """)
    print('Session parent_job_id check:')
    for r in rows:
        sid = str(r['id'])[:8]
        parent = str(r['parent_job_id'])[:8] if r['parent_job_id'] else 'NULL'
        print(f"  {sid} parent={parent} status={r['status']}")

    count = await conn.fetchval('SELECT COUNT(*) FROM agent_run_relationships')
    print(f'agent_run_relationships total rows: {count}')

    await conn.close()

asyncio.run(main())
