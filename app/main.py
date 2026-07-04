from fastapi import FastAPI, HTTPException
from app.db import get_pool
from app.schemas import JobCreate
import json

app = FastAPI(title="Task Queue")

@app.get("/health")
async def health():
    pool = await get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM jobs")
    return {"status": "ok", "jobs_in_db": count}

@app.post("/jobs")
async def enqueue(job: JobCreate):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO jobs (task_name, payload)
            VALUES ($1, $2)
            RETURNING id, status
            """,
            job.task_name,
            json.dumps(job.payload),
        )
    return {"id": row["id"], "status": row["status"]}

@app.get("/stats")
async def stats():
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, count(*) AS n FROM jobs GROUP BY status"
        )
    return {row["status"]: row["n"] for row in rows}

@app.get("/jobs/{job_id}")
async def get_job(job_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, task_name, status, attempts, max_attempts, last_error, created_at, updated_at FROM jobs WHERE id = $1",
            job_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return dict(row)