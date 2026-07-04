import asyncio
import os
import random
import asyncpg

async def fetch_one_job(conn):
    row = await conn.fetchrow(
        """
        UPDATE jobs
        SET status = 'running', claimed_at = now(), updated_at = now()
        WHERE id = (
            SELECT id FROM jobs
            WHERE status = 'queued'
              AND run_after <= now()
            ORDER BY id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id, task_name, payload, attempts, max_attempts
        """
    )
    return row

async def process(job):
    print(f"Processing job {job['id']}: {job['task_name']} (attempt {job['attempts'] + 1})", flush=True)
    if random.random() < 0.5:
        raise RuntimeError("simulated failure")
    await asyncio.sleep(30)

async def mark_done(conn, job_id):
    await conn.execute(
        "UPDATE jobs SET status = 'done', updated_at = now() WHERE id = $1",
        job_id,
    )

async def mark_failed(conn, job, error_msg):
    new_attempts = job["attempts"] + 1
    backoff_seconds = 2 ** (new_attempts - 1)
    await conn.execute(
        """
        UPDATE jobs
        SET status = 'queued',
            attempts = $2,
            run_after = now() + ($3 * interval '1 second'),
            last_error = $4,
            updated_at = now()
        WHERE id = $1
        """,
        job["id"], new_attempts, backoff_seconds, str(error_msg),
    )
    print(f"Job {job['id']} failed ({error_msg}), retrying in {backoff_seconds}s (attempt {new_attempts})", flush=True)

async def main():
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    print("Worker started, waiting for jobs...", flush=True)
    while True:
        async with pool.acquire() as conn:
            job = await fetch_one_job(conn)
            if job is None:
                await asyncio.sleep(1)
                continue
            try:
                await process(job)
                await mark_done(conn, job["id"])
            except Exception as e:
                print(f"Job {job['id']} error: {e}", flush=True)
                await mark_failed(conn, job, e)

if __name__ == "__main__":
    asyncio.run(main())