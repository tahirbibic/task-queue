from fastapi import FastAPI
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