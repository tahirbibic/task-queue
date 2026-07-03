import asyncio
import os
import asyncpg

async def fetch_one_job(conn):
    """
    Find the oldest queued job, mark it running, and return it.
    Returns the job row, or None if the queue is empty.
    """
    row = await conn.fetchrow(
        """
        UPDATE jobs
        SET status = 'running', updated_at = now()
        WHERE id = (
        SELECT id FROM jobs
        WHERE status = 'queued'
        ORDER BY id
        LIMIT 1
        )
        RETURNING id, task_name, payload
        """
    )
    return row

async def process(job):
    print(f"Processing job {job['id']}: {job['task_name']} {job['payload']}", flush=True)
    await asyncio.sleep(1)

async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"])
    print("Worker started, waiting for jobs...", flush=True)
    while True:
        async with pool.acquire() as conn:
            job = await fetch_one_job(conn)
            if job is None:
                await asyncio.sleep(1)
                continue
            await process(job)
            await conn.execute(
                "UPDATE jobs SET status = 'done', updated_at = now() WHERE id = $1",
                job["id"],
            )

if __name__ == "__main__":
    asyncio.run(main())