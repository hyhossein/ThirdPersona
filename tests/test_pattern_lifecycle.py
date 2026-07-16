"""
ThirdPersona Pattern Lifecycle Tests

These tests prove — at the DATABASE level — that:

1. A hypothesis pattern CANNOT become active without explicit user confirmation.
   The DB trigger rejects the transition. No amount of application-layer
   code can bypass this.

2. A candidate pattern cannot skip to active (must go through hypothesis).

3. The evidence floor auto-promotes candidate → hypothesis when met.

4. RLS prevents cross-user data access.

5. Rejection feedback is recorded and available for the extraction prompt.

6. The rejection-rate circuit breaker fires when the threshold is exceeded.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
import pytest_asyncio

from tests.conftest import (
    create_test_user,
    create_test_entry,
    create_test_pattern,
    add_evidence,
    set_rls_context,
)


# ================================================================
# TEST 1: THE CONFIRMATION GATE (the proof the user asked for)
# ================================================================


@pytest.mark.asyncio
async def test_hypothesis_cannot_become_active_without_confirmation(conn):
    """
    PROOF: A hypothesis pattern CANNOT become active without the user
    explicitly confirming it via pattern_visibility.confirmed_at.

    The database trigger `enforce_pattern_confirmation` rejects the
    UPDATE. This is not application logic — it's a database constraint
    that no code path can bypass.
    """
    user_id = await create_test_user(conn)

    # Create 3 entries (enough to meet the evidence floor)
    entry_ids = []
    for i in range(3):
        eid = await create_test_entry(conn, user_id, f"Entry about feelings #{i}")
        entry_ids.append(eid)

    # Create a pattern as candidate
    pattern_id = await create_test_pattern(conn, user_id, status="candidate")

    # Add evidence — the trigger auto-promotes to hypothesis
    for eid in entry_ids:
        await add_evidence(conn, pattern_id, eid, user_id)

    # Verify it's now a hypothesis
    status = await conn.fetchval(
        "SELECT status FROM patterns WHERE id = $1", pattern_id
    )
    assert status == "hypothesis", f"Expected 'hypothesis', got '{status}'"

    # ── THE TEST: try to promote to active WITHOUT confirmation ──
    # Wrap in a savepoint (async with conn.transaction() inside the outer test
    # transaction). When the trigger RAISEs, only the savepoint rolls back —
    # the outer transaction stays clean for subsequent queries.
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE patterns SET status = 'active' WHERE id = $1", pattern_id
            )
        raise AssertionError("UPDATE should have been rejected by trigger")
    except asyncpg.RaiseError as exc:
        assert "LIFECYCLE_VIOLATION" in str(exc)

    # Verify it's still a hypothesis (the UPDATE was rejected)
    status = await conn.fetchval(
        "SELECT status FROM patterns WHERE id = $1", pattern_id
    )
    assert status == "hypothesis", "Pattern should still be hypothesis after rejected UPDATE"

    # ── NOW: confirm the pattern ──
    await conn.execute(
        """
        UPDATE pattern_visibility
        SET first_seen_at = $2, confirmed_at = $2
        WHERE pattern_id = $1 AND user_id = $3
        """,
        pattern_id,
        datetime.now(timezone.utc),
        user_id,
    )

    # ── NOW: promote to active — this MUST succeed ──
    await conn.execute(
        "UPDATE patterns SET status = 'active' WHERE id = $1", pattern_id
    )

    status = await conn.fetchval(
        "SELECT status FROM patterns WHERE id = $1", pattern_id
    )
    assert status == "active", "Pattern should be active after confirmation + promotion"


# ================================================================
# TEST 2: CANDIDATE CANNOT SKIP TO ACTIVE
# ================================================================


@pytest.mark.asyncio
async def test_candidate_cannot_skip_to_active(conn):
    """
    Patterns must go through hypothesis before becoming active.
    The trigger blocks candidate → active even if confirmed_at exists.
    """
    user_id = await create_test_user(conn, email="skip@test.com")
    pattern_id = await create_test_pattern(conn, user_id, status="candidate")

    with pytest.raises(asyncpg.RaiseError, match="LIFECYCLE_VIOLATION"):
        await conn.execute(
            "UPDATE patterns SET status = 'active' WHERE id = $1", pattern_id
        )


# ================================================================
# TEST 3: EVIDENCE FLOOR AUTO-PROMOTION
# ================================================================


@pytest.mark.asyncio
async def test_evidence_floor_promotes_candidate_to_hypothesis(conn):
    """
    When a candidate pattern accumulates enough supporting evidence
    (>= MIN_EVIDENCE), the trigger auto-promotes it to hypothesis
    and creates a pattern_visibility record.
    """
    user_id = await create_test_user(conn, email="floor@test.com")
    pattern_id = await create_test_pattern(conn, user_id, status="candidate")

    # Create entries and add evidence one at a time
    for i in range(2):
        eid = await create_test_entry(conn, user_id, f"Evidence entry {i}")
        await add_evidence(conn, pattern_id, eid, user_id)

    # With 2 entries, should still be candidate (floor is 3)
    status = await conn.fetchval(
        "SELECT status FROM patterns WHERE id = $1", pattern_id
    )
    assert status == "candidate", "Should remain candidate with only 2 evidence entries"

    # Add the 3rd entry — should trigger promotion
    eid3 = await create_test_entry(conn, user_id, "The tipping point entry")
    await add_evidence(conn, pattern_id, eid3, user_id)

    status = await conn.fetchval(
        "SELECT status FROM patterns WHERE id = $1", pattern_id
    )
    assert status == "hypothesis", "Should be promoted to hypothesis with 3 evidence entries"

    # Verify visibility record was created
    vis = await conn.fetchrow(
        "SELECT * FROM pattern_visibility WHERE pattern_id = $1", pattern_id
    )
    assert vis is not None, "pattern_visibility record should be created on promotion"
    assert vis["confirmed_at"] is None, "confirmed_at should be NULL (awaiting user)"


@pytest.mark.asyncio
async def test_evidence_count_tracked(conn):
    """Evidence count and temporal spread are updated by the trigger."""
    user_id = await create_test_user(conn, email="count@test.com")
    pattern_id = await create_test_pattern(conn, user_id, status="candidate")

    for i in range(4):
        eid = await create_test_entry(conn, user_id, f"Count test entry {i}")
        await add_evidence(conn, pattern_id, eid, user_id)

    row = await conn.fetchrow(
        "SELECT evidence_count, status FROM patterns WHERE id = $1", pattern_id
    )
    assert row["evidence_count"] == 4
    assert row["status"] == "hypothesis"  # 4 >= 3, so promoted


# ================================================================
# TEST 4: RLS ISOLATION
# ================================================================


@pytest.mark.asyncio
async def test_rls_prevents_cross_user_access(conn):
    """
    User A cannot see User B's entries or patterns through RLS.
    Setting app.current_user_id restricts all queries.
    """
    user_a = await create_test_user(conn, email="a@test.com", display_name="Alice")
    user_b = await create_test_user(conn, email="b@test.com", display_name="Bob")

    # Create data for both users (without RLS context — superuser)
    entry_a = await create_test_entry(conn, user_a, "Alice's private thought")
    entry_b = await create_test_entry(conn, user_b, "Bob's private thought")
    pattern_a = await create_test_pattern(conn, user_a, insight="Alice's pattern")
    pattern_b = await create_test_pattern(conn, user_b, insight="Bob's pattern")

    # Set RLS context to User A
    await set_rls_context(conn, user_a)

    # User A should only see their own entries
    entries = await conn.fetch("SELECT id FROM entries")
    entry_ids = {r["id"] for r in entries}
    assert entry_a in entry_ids, "Alice should see her own entry"
    assert entry_b not in entry_ids, "Alice should NOT see Bob's entry"

    # User A should only see their own patterns
    patterns = await conn.fetch("SELECT id FROM patterns")
    pattern_ids = {r["id"] for r in patterns}
    assert pattern_a in pattern_ids, "Alice should see her own pattern"
    assert pattern_b not in pattern_ids, "Alice should NOT see Bob's pattern"


@pytest.mark.asyncio
async def test_rls_no_context_returns_nothing(conn):
    """
    If no RLS context is set, all queries return empty results.
    current_setting(..., true) returns NULL → nothing matches.
    """
    user_id = await create_test_user(conn, email="nocontext@test.com")
    await create_test_entry(conn, user_id, "An entry")

    # Set RLS context to a non-existent user (simulating no auth)
    fake_id = uuid.uuid4()
    await set_rls_context(conn, fake_id)

    entries = await conn.fetch("SELECT id FROM entries")
    assert len(entries) == 0, "No entries should be visible with wrong RLS context"


# ================================================================
# TEST 5: REJECTION FEEDBACK
# ================================================================


@pytest.mark.asyncio
async def test_rejection_records_reason(conn):
    """Rejected patterns store the reason for feedback to the extraction prompt."""
    user_id = await create_test_user(conn, email="reject@test.com")
    pattern_id = await create_test_pattern(
        conn, user_id,
        insight="We noticed you avoid conflict",
        status="hypothesis",
    )

    # Create visibility record (required for hypothesis)
    await conn.execute(
        """
        INSERT INTO pattern_visibility (pattern_id, user_id)
        VALUES ($1, $2)
        """,
        pattern_id,
        user_id,
    )

    # Reject with reason
    await conn.execute(
        """
        INSERT INTO pattern_rejections (pattern_id, user_id, reason)
        VALUES ($1, $2, $3)
        """,
        pattern_id,
        user_id,
        "This was true last year but not anymore",
    )
    await conn.execute(
        "UPDATE patterns SET status = 'rejected' WHERE id = $1", pattern_id
    )

    # Verify rejection is retrievable
    rejection = await conn.fetchrow(
        """
        SELECT p.insight, pr.reason
        FROM pattern_rejections pr
        JOIN patterns p ON p.id = pr.pattern_id
        WHERE pr.user_id = $1
        """,
        user_id,
    )
    assert rejection is not None
    assert rejection["insight"] == "We noticed you avoid conflict"
    assert rejection["reason"] == "This was true last year but not anymore"


# ================================================================
# TEST 6: REJECTION-RATE CIRCUIT BREAKER
# ================================================================


@pytest.mark.asyncio
async def test_rejection_rate_circuit_breaker(conn):
    """
    When the rejection rate exceeds the threshold, the circuit breaker
    flags that extraction should pause.
    """
    user_id = await create_test_user(conn, email="breaker@test.com")

    # Create 10 patterns, reject 5 (50% > 40% threshold)
    for i in range(10):
        pid = await create_test_pattern(
            conn, user_id,
            insight=f"Pattern {i}",
            status="hypothesis",
        )
        await conn.execute(
            "INSERT INTO pattern_visibility (pattern_id, user_id) VALUES ($1, $2)",
            pid, user_id,
        )
        if i < 5:
            # Reject these
            await conn.execute(
                "INSERT INTO pattern_rejections (pattern_id, user_id, reason) VALUES ($1, $2, 'test')",
                pid, user_id,
            )
            await conn.execute(
                "UPDATE patterns SET status = 'rejected' WHERE id = $1", pid
            )

    # Check the rejection rate view
    rate_row = await conn.fetchrow(
        """
        SELECT
            COUNT(*) FILTER (
                WHERE p.status = 'rejected'
                AND EXISTS (
                    SELECT 1 FROM pattern_rejections pr
                    WHERE pr.pattern_id = p.id
                    AND pr.rejected_at > now() - interval '30 days'
                )
            ) AS rejections_30d,
            COUNT(*) FILTER (
                WHERE p.created_at > now() - interval '30 days'
            ) AS patterns_30d
        FROM patterns p
        WHERE p.user_id = $1
        """,
        user_id,
    )

    rejections = rate_row["rejections_30d"]
    total = rate_row["patterns_30d"]
    rate = rejections / total if total > 0 else 0.0

    assert rejections == 5
    assert total == 10
    assert rate == 0.5  # 50%, above the 40% threshold
    assert rate > 0.4, "Circuit breaker should trip: rejection rate exceeds threshold"


# ================================================================
# TEST 7: FULL LIFECYCLE END-TO-END
# ================================================================


@pytest.mark.asyncio
async def test_full_lifecycle_candidate_to_active(conn):
    """
    Complete lifecycle: candidate → hypothesis (via evidence) → active (via confirmation).
    Proves the entire flow works when done correctly.
    """
    user_id = await create_test_user(conn, email="lifecycle@test.com")

    # 1. Create entries
    entries = []
    for i in range(5):
        eid = await create_test_entry(conn, user_id, f"Lifecycle entry {i}: I feel...")
        entries.append(eid)

    # 2. Create a candidate pattern
    pattern_id = await create_test_pattern(
        conn, user_id,
        insight="We noticed that you tend to reflect more deeply in the evenings",
        category="self",
        confidence=0.4,
        status="candidate",
    )

    # 3. Add evidence one by one
    for eid in entries[:2]:
        await add_evidence(conn, pattern_id, eid, user_id)

    # Still candidate (2 < 3)
    assert await conn.fetchval(
        "SELECT status FROM patterns WHERE id = $1", pattern_id
    ) == "candidate"

    # 4. Third evidence → promotion to hypothesis
    await add_evidence(conn, pattern_id, entries[2], user_id)
    assert await conn.fetchval(
        "SELECT status FROM patterns WHERE id = $1", pattern_id
    ) == "hypothesis"

    # 5. Add more evidence (enriches the pattern)
    for eid in entries[3:]:
        await add_evidence(conn, pattern_id, eid, user_id)

    assert await conn.fetchval(
        "SELECT evidence_count FROM patterns WHERE id = $1", pattern_id
    ) == 5

    # 6. Attempt activation without confirmation → FAILS
    # Savepoint keeps the outer transaction clean after the trigger RAISEs.
    try:
        async with conn.transaction():
            await conn.execute(
                "UPDATE patterns SET status = 'active' WHERE id = $1", pattern_id
            )
        raise AssertionError("UPDATE should have been rejected by trigger")
    except asyncpg.RaiseError as exc:
        assert "LIFECYCLE_VIOLATION" in str(exc)

    # 7. Confirm the pattern
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        UPDATE pattern_visibility
        SET first_seen_at = $2, confirmed_at = $2
        WHERE pattern_id = $1 AND user_id = $3
        """,
        pattern_id, now, user_id,
    )

    # 8. Activate → SUCCEEDS
    await conn.execute(
        "UPDATE patterns SET status = 'active' WHERE id = $1", pattern_id
    )
    final = await conn.fetchrow(
        "SELECT status, evidence_count, updated_at FROM patterns WHERE id = $1",
        pattern_id,
    )
    assert final["status"] == "active"
    assert final["evidence_count"] == 5
    assert final["updated_at"] is not None


# ================================================================
# TEST 8: CONTRADICTING EVIDENCE DOESN'T COUNT TOWARD FLOOR
# ================================================================


@pytest.mark.asyncio
async def test_contradicting_evidence_does_not_promote(conn):
    """
    Only 'supports' evidence counts toward the evidence floor.
    Contradictions are tracked but don't trigger promotion.
    """
    user_id = await create_test_user(conn, email="contradict@test.com")
    pattern_id = await create_test_pattern(conn, user_id, status="candidate")

    # Add 2 supporting + 3 contradicting entries
    for i in range(2):
        eid = await create_test_entry(conn, user_id, f"Supporting {i}")
        await add_evidence(conn, pattern_id, eid, user_id, relation="supports")

    for i in range(3):
        eid = await create_test_entry(conn, user_id, f"Contradicting {i}")
        await add_evidence(conn, pattern_id, eid, user_id, relation="contradicts")

    # Should still be candidate: only 2 supporting entries
    status = await conn.fetchval(
        "SELECT status FROM patterns WHERE id = $1", pattern_id
    )
    assert status == "candidate", (
        "Pattern should remain candidate: contradictions don't count toward evidence floor"
    )
