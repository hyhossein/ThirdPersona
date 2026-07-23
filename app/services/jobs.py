"""
Background job queue — the 11pm loop.

A person writes at night; extraction runs minutes later in the background;
they wake up to a hypothesis. Postgres-native (SKIP LOCKED claiming), no
extra infrastructure — but deliberately SHAPED like Temporal:

    one jobs row            ~= one workflow execution
    ACTIVITIES dict         ~= registered activities
    claim/execute/backoff   ~= activity retry policy

When the consent layer ships and Temporal enters the stack (ADR-001),
each activity function ports as-is into a Temporal activity and this
module retires.

Security invariant: the worker NEVER bypasses RLS. The jobs table holds
metadata only (no diary content); to execute a job the worker assumes
that one user's RLS context via set_config, exactly like an API request.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import asyncpg

from app.services.extraction import run_extraction

logger = logging.getLogger(__name__)

BATCH_WINDOW_SECONDS = 120     # write burst coalescing: run 2 min after the first write
RETRY_BACKOFF_BASE = 60        # 60s, 120s, 240s ...
MIN_ENTRIES_FOR_EXTRACTION = 3


# ---------------------------------------------------------------
# Enqueue (called from the API, inside the user's request)
# ---------------------------------------------------------------
async def enqueue_extraction(conn: asyncpg.Connection, user_id: uuid.UUID) -> bool:
    """
    Queue an extraction for this user, debounced: if one is already
    queued, this write will be covered by it. Returns True if a new
    job was created.
    """
    count = await conn.fetchval(
        "SELECT COUNT(*) FROM entries WHERE user_id = $1", user_id
    )
    if count < MIN_ENTRIES_FOR_EXTRACTION:
        return False
    row = await conn.fetchrow(
        """
        INSERT INTO jobs (user_id, kind, run_at)
        VALUES ($1, 'extract', now() + make_interval(secs => $2))
        ON CONFLICT (user_id, kind) WHERE status = 'queued'
        DO NOTHING
        RETURNING id
        """,
        user_id,
        BATCH_WINDOW_SECONDS,
    )
    return row is not None


# ---------------------------------------------------------------
# Activities (Temporal-shaped: one async fn per unit of real work)
# ---------------------------------------------------------------
async def activity_run_extraction(conn: asyncpg.Connection, user_id: uuid.UUID) -> str:
    """Runs INSIDE the user's RLS context (worker sets it before calling)."""
    result = await run_extraction(conn, user_id)
    return result.message


ACTIVITIES = {
    "extract": activity_run_extraction,
}


# ---------------------------------------------------------------
# Worker (claim -> execute under user context -> settle)
# ---------------------------------------------------------------
async def claim_next_job(conn: asyncpg.Connection):
    """Atomically claim the oldest due job. SKIP LOCKED = safe concurrency."""
    return await conn.fetchrow(
        """
        UPDATE jobs SET status = 'running', attempts = attempts + 1, updated_at = now()
        WHERE id = (
            SELECT id FROM jobs
            WHERE status = 'queued' AND run_at <= now()
            ORDER BY run_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        RETURNING id, user_id, kind, attempts, max_attempts
        """
    )


async def execute_job(conn: asyncpg.Connection, job) -> None:
    """Execute one claimed job inside its user's RLS context."""
    activity = ACTIVITIES[job["kind"]]
    try:
        async with conn.transaction():
            # Assume this one user's identity for the duration — the same
            # mechanism as an authenticated API request. Never BYPASSRLS.
            await conn.execute(
                "SELECT set_config('app.current_user_id', $1, true)",
                str(job["user_id"]),
            )
            message = await activity(conn, job["user_id"])
        await conn.execute(
            "UPDATE jobs SET status = 'done', updated_at = now(), last_error = NULL WHERE id = $1",
            job["id"],
        )
        logger.info("job %s done: %s", job["id"], message)
    except Exception as exc:  # noqa: BLE001 — job isolation: one failure never kills the worker
        if job["attempts"] >= job["max_attempts"]:
            await conn.execute(
                "UPDATE jobs SET status = 'failed', last_error = $2, updated_at = now() WHERE id = $1",
                job["id"], str(exc)[:800],
            )
            logger.error("job %s failed permanently: %s", job["id"], exc)
        else:
            backoff = RETRY_BACKOFF_BASE * (2 ** (job["attempts"] - 1))
            await conn.execute(
                """
                UPDATE jobs SET status = 'queued', last_error = $2,
                       run_at = now() + make_interval(secs => $3), updated_at = now()
                WHERE id = $1
                """,
                job["id"], str(exc)[:800], backoff,
            )
            logger.warning("job %s retry in %ss: %s", job["id"], backoff, exc)


async def work_once(conn: asyncpg.Connection) -> bool:
    """Claim and execute at most one job. Returns True if one was processed."""
    job = await claim_next_job(conn)
    if job is None:
        return False
    await execute_job(conn, job)
    return True


async def worker_loop(dsn: str, poll_seconds: float = 2.0, stop_event: asyncio.Event | None = None):
    """Long-running worker: connects as the app role (RLS applies)."""
    conn = await asyncpg.connect(dsn)
    logger.info("worker started")
    try:
        while stop_event is None or not stop_event.is_set():
            try:
                worked = await work_once(conn)
            except (asyncpg.PostgresConnectionError, ConnectionError):
                logger.warning("worker lost DB connection; reconnecting")
                await asyncio.sleep(2)
                conn = await asyncpg.connect(dsn)
                continue
            if not worked:
                await asyncio.sleep(poll_seconds)
    finally:
        await conn.close()
        logger.info("worker stopped")
