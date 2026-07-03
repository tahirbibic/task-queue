import asyncio, httpx

async def enqueue(client, i):
    await client.post(
        "http://localhost:8000/jobs",
        json={"task_name": "send_email", "payload": {"n": i}},
    )

async def main():
    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[enqueue(client, i) for i in range(30)])
    print("enqueued 30 jobs")

asyncio.run(main())