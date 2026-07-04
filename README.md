# task-queue

A distributed task queue built on PostgreSQL and FastAPI, with exactly-once job
processing, automatic retries with backoff, crash recovery, and a dead-letter
queue. Built to explore how production job queues stay reliable under
concurrency and failure — using Postgres as the broker instead of a dedicated
message queue.

## Why Postgres as a queue

Most task queues reach for Redis, RabbitMQ, or Kafka. This one deliberately uses
Postgres, because for moderate throughput a database you already run can be the
queue, one less piece of infrastructure to operate. The feature that makes this
viable is `SELECT ... FOR UPDATE SKIP LOCKED`, which lets many workers claim
different jobs concurrently without colliding or blocking. The tradeoff: a
dedicated broker scales further; the throughput ceiling where I'd switch is worth
knowing, but for most workloads the operational simplicity wins.

## Architecture

Three process types share one database:

- **API** (FastAPI) — enqueues jobs and exposes status endpoints (producer)
- **Workers** (scalable, run N in parallel) — claim and execute jobs (consumers)
- **Reaper** — periodically recovers jobs orphaned by crashed workers

```
          enqueue                    claim (SKIP LOCKED)
  client ---------> [ API ] ---> ( Postgres: jobs ) <--- [ Worker x N ]
                                        ^
                                        | sweep for orphaned jobs
                                     [ Reaper ]
```

Jobs move through a state machine: `queued` -> `running` -> `done`, with
`failed` jobs returning to `queued` (with a delay) and permanently-failing jobs
ending in `dead`.

## The three hard problems it solves

Each of these was built by first writing the naive version, observing it fail
under load, then fixing it.

### 1. Double-processing (concurrency)

With a naive "find the oldest queued job, then mark it running" claim, multiple
workers read the same job in the gap between the read and the write, and all
process it. Measured with 3 workers and 30 jobs: **[YOUR NUMBER] of the 30 jobs
were processed by more than one worker.**

Fixed by claiming with a single atomic statement using `FOR UPDATE SKIP LOCKED`:
each worker locks the row it claims, and other workers skip locked rows and grab
different jobs instead of blocking. Result under identical load: **zero
duplicates**, full parallelism, no waiting.

### 2. Lost jobs on worker crash

When a worker claims a job (`status = 'running'`) and then dies before finishing,
the job is stranded in `running` forever — no worker will pick it up, and it
never completes. Retry logic can't help, because a dead process raises no
exception to catch.

Fixed with a **visibility timeout**: each claimed job records `claimed_at`, and a
reaper process requeues any job that has been `running` longer than the timeout
(assuming its worker died). Demonstrated by killing a worker mid-job with
`docker kill` and watching the reaper requeue the job and a surviving worker
finish it.

### 3. Poison jobs (infinite retries)

A job that fails permanently (bad payload, deleted record, a bug) would retry
forever, wasting workers. Fixed with a **dead-letter queue**: after
`max_attempts`, the job is moved to a terminal `dead` state with its last error
preserved, rather than being requeued. Dead jobs can be inspected and, in a real
system, replayed after the root cause is fixed.

## Design decisions & tradeoffs

- **Postgres over Redis/RabbitMQ** — removes a piece of infrastructure;
  `SKIP LOCKED` makes it correct under concurrency. A dedicated broker scales
  further, which is the reason to switch at high throughput.
- **Raw SQL (asyncpg) over an ORM** — the queue's core is a Postgres-specific
  locking query (`FOR UPDATE SKIP LOCKED` + `RETURNING`). An ORM would wrap that
  in raw SQL anyway and add overhead; keeping the SQL explicit makes the locking
  semantics — which are central to correctness — visible. For a normal CRUD
  service I'd use an ORM; this is a deliberate exception.
- **At-least-once delivery** — the reaper cannot distinguish "worker died" from
  "worker is slow," so a slow-but-alive worker's job can be requeued and run
  twice. The mitigation is idempotent jobs plus a visibility timeout set above
  the realistic maximum job duration.
- **Exponential backoff** — failed jobs retry after 1s, 2s, 4s... so a failing
  downstream dependency gets exponentially more room to recover instead of being
  hammered.
- **Single reaper** — one reaper avoids reapers racing each other. For high
  availability I'd run multiple with `SKIP LOCKED` on the sweep, or leader
  election.

## Schema

The `jobs` table carries everything the state machine needs: `status`,
`attempts`/`max_attempts`, `run_after` (for backoff scheduling), `claimed_at`
(for the visibility timeout), and `last_error` (for debugging dead jobs).

## API

| Method | Path          | Purpose                              |
|--------|---------------|--------------------------------------|
| POST   | `/jobs`       | Enqueue a job (validated by Pydantic)|
| GET    | `/jobs/{id}`  | Inspect a single job's full state    |
| GET    | `/stats`      | Job counts by status (queue depth)   |
| GET    | `/health`     | Liveness + DB connectivity           |

## Running it

```bash
docker compose up --build --scale worker=3
```

Enqueue a job:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"task_name": "send_email", "payload": {"to": "a@b.com"}}'
```

Watch the queue drain:

```bash
curl http://localhost:8000/stats
# {"queued": 5, "running": 3, "done": 18, "dead": 4}
```

### Try the crash recovery

1. Enqueue a slow job and note which worker claims it.
2. `docker kill task-queue-worker-<n>` while it's running.
3. Watch the reaper requeue the orphaned job and a surviving worker finish it.

## Stack

FastAPI · PostgreSQL · asyncpg · Docker · Pydantic

## Notes

- Schema is applied via `schema.sql` on first startup. In a production system I'd
  use a migration tool (e.g. Alembic) instead of recreating the volume.
- The worker's `process()` includes a simulated failure rate for demonstrating
  retries and dead-lettering; real tasks would replace it with actual work.