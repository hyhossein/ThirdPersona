"""
Job queue tests — the 11pm loop.

  1. Enqueue is debounced: many writes, one queued job.
  2. Enqueue respects the entry floor (no extraction below 3 entries).
  3. The worker executes a due job under the RIGHT user's RLS context.
  4. A failing job retries with backoff, then fails permanently.
  5. One user's failing job never blocks another user's job.
"""

from __future__ import annotations

import uuid

import pytest

import app.services.jobs as jobs
from app.services.jobs import (
    enqueue_extraction,
    claim_next_job,
    work_once,
)
from tests.conftest import create_test_user, create_test_entry


async def _make_due(conn, user_id):
    """Collapse the batch window so the job is claimable now."""
    await conn.execute(
        "UPDATE jobs SET run_at = now() - interval '1 second' WHERE user_id = $1 AND status = 'queued'",
        user_id,
    )


@pytest.mark.asyncio
async def test_enqueue_is_debounced(conn):
    user = await create_test_user(conn, email=f"jq-{uuid.uuid4()}@t.co")
    for i in range(4):
        await create_test_entry(conn, user, f"entry {i} about my evening")
    created = [await enqueue_extraction(conn, user) for _ in range(5)]
    assert created[0] is True
    assert all(c is False for c in created[1:]), "only one queued job per user"
    n = await conn.fetchval(
        "SELECT COUNT(*) FROM jobs WHERE user_id = $1 AND status = 'queued'", user
    )
    assert n == 1


@pytest.mark.asyncio
async def test_enqueue_respects_entry_floor(conn):
    user = await create_test_user(conn, email=f"jq-{uuid.uuid4()}@t.co")
    await create_test_entry(conn, user, "only one entry")
    assert await enqueue_extraction(conn, user) is False
    n = await conn.fetchval("SELECT COUNT(*) FROM jobs WHERE user_id = $1", user)
    assert n == 0


@pytest.mark.asyncio
async def test_worker_runs_job_under_right_user_context(conn, monkeypatch):
    user_a = await create_test_user(conn, email=f"jq-{uuid.uuid4()}@t.co")
    user_b = await create_test_user(conn, email=f"jq-{uuid.uuid4()}@t.co")
    for i in range(3):
        await create_test_entry(conn, user_a, f"A's entry {i}")

    seen = []

    async def spy_activity(c, uid):
        ctx = await c.fetchval("SELECT current_setting('app.current_user_id', true)")
        seen.append((uid, ctx))
        return "ok"

    monkeypatch.setitem(jobs.ACTIVITIES, "extract", spy_activity)

    await enqueue_extraction(conn, user_a)
    await _make_due(conn, user_a)
    assert await work_once(conn) is True

    assert len(seen) == 1
    uid, ctx = seen[0]
    assert uid == user_a
    assert ctx == str(user_a), "activity must run inside the job owner's RLS context"
    assert uid != user_b

    status = await conn.fetchval("SELECT status FROM jobs WHERE user_id = $1", user_a)
    assert status == "done"


@pytest.mark.asyncio
async def test_failing_job_retries_then_fails(conn, monkeypatch):
    user = await create_test_user(conn, email=f"jq-{uuid.uuid4()}@t.co")
    for i in range(3):
        await create_test_entry(conn, user, f"entry {i}")

    async def bad_activity(c, uid):
        raise RuntimeError("LLM exploded")

    monkeypatch.setitem(jobs.ACTIVITIES, "extract", bad_activity)
    await enqueue_extraction(conn, user)

    for attempt in range(1, 4):
        await _make_due(conn, user)
        assert await work_once(conn) is True
        row = await conn.fetchrow(
            "SELECT status, attempts, last_error FROM jobs WHERE user_id = $1", user
        )
        assert row["attempts"] == attempt
        assert "LLM exploded" in row["last_error"]
        if attempt < 3:
            assert row["status"] == "queued", "should requeue with backoff"
        else:
            assert row["status"] == "failed", "should fail permanently at max_attempts"


@pytest.mark.asyncio
async def test_one_users_failure_does_not_block_another(conn, monkeypatch):
    user_bad = await create_test_user(conn, email=f"jq-{uuid.uuid4()}@t.co")
    user_good = await create_test_user(conn, email=f"jq-{uuid.uuid4()}@t.co")
    for i in range(3):
        await create_test_entry(conn, user_bad, f"bad {i}")
        await create_test_entry(conn, user_good, f"good {i}")

    async def selective(c, uid):
        if uid == user_bad:
            raise RuntimeError("boom")
        return "ok"

    monkeypatch.setitem(jobs.ACTIVITIES, "extract", selective)
    await enqueue_extraction(conn, user_bad)
    await enqueue_extraction(conn, user_good)
    await _make_due(conn, user_bad)
    await _make_due(conn, user_good)

    assert await work_once(conn) is True
    assert await work_once(conn) is True

    good_status = await conn.fetchval("SELECT status FROM jobs WHERE user_id = $1", user_good)
    assert good_status == "done", "good user's job completes despite bad user's failure"


@pytest.mark.asyncio
async def test_claim_ignores_future_jobs(conn):
    user = await create_test_user(conn, email=f"jq-{uuid.uuid4()}@t.co")
    for i in range(3):
        await create_test_entry(conn, user, f"entry {i}")
    await enqueue_extraction(conn, user)  # run_at is now + batch window
    job = await claim_next_job(conn)
    assert job is None, "jobs inside the batch window must not be claimed early"
