import asyncio
import os
import asyncpg

VISIBILITY_TIMEOUT_SECONDS = 10
SWEEP_INTERVAL_SECONDS = 3

async def reap_orphaned_jobs(conn):
    rows = await conn.fetch(
    """
    UPDATE jobs
    SET
        status = 'queued',
        attempts = attempts + 1,
        claimed_at = NULL,
        updated_at = now()
    WHERE status = 'running'
      AND claimed_at < now() - ($1 * interval '1 second')
    RETURNING id
    """,
    VISIBILITY_TIMEOUT_SECONDS,
    )
    return rows

async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    print("Reaper started, sweeping for orphaned jobs...", flush=True)
    while True:
        async with pool.acquire() as conn:
            reaped = await reap_orphaned_jobs(conn)
            for row in reaped:
                print(f"Reaped orphaned job {row['id']} — requeued", flush=True)
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)

if __name__ == "__main__":
    asyncio.run(main())