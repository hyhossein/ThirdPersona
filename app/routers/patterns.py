"""
Pattern lifecycle endpoints.

Lifecycle: candidate → hypothesis → active (requires confirmation)
                                  → rejected (user says "not me")
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
import asyncpg

from app.database import get_db, get_current_user_id
from app.schemas import (
    PatternResponse,
    PatternEvidenceResponse,
    PatternConfirmRequest,
    PatternRejectRequest,
    ExtractionResult,
    ValidationStatus,
)
from app.services.extraction import run_extraction
from app.services.validation import check_rejection_rate

router = APIRouter(prefix="/patterns", tags=["patterns"])


@router.get("", response_model=list[PatternResponse])
async def list_patterns(
    status: str | None = None,
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    List the user's patterns. Filter by status to see only hypotheses,
    active patterns, etc. RLS restricts to the authenticated user.
    """
    if status:
        rows = await conn.fetch(
            """
            SELECT id, user_id, insight, category, confidence, domains,
                   temporal_trend, status, evidence_count, temporal_spread,
                   specificity, is_tension, first_seen, last_evidence, created_at
            FROM patterns
            WHERE status = $1
            ORDER BY confidence DESC, last_evidence DESC NULLS LAST
            """,
            status,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, user_id, insight, category, confidence, domains,
                   temporal_trend, status, evidence_count, temporal_spread,
                   specificity, is_tension, first_seen, last_evidence, created_at
            FROM patterns
            WHERE status IN ('hypothesis', 'active')
            ORDER BY
                CASE status WHEN 'hypothesis' THEN 0 ELSE 1 END,
                confidence DESC,
                last_evidence DESC NULLS LAST
            """,
        )
    return [PatternResponse(**dict(r)) for r in rows]


@router.get("/{pattern_id}/evidence", response_model=list[PatternEvidenceResponse])
async def get_evidence(
    pattern_id: uuid.UUID,
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Traceability: show the entries that support/contradict this pattern.
    The user sees WHY the system believes what it believes.
    """
    rows = await conn.fetch(
        """
        SELECT pe.entry_id, pe.relation, pe.weight, pe.created_at,
               e.text_content AS entry_text
        FROM pattern_evidence pe
        JOIN entries e ON e.id = pe.entry_id
        WHERE pe.pattern_id = $1
        ORDER BY pe.weight DESC, pe.created_at DESC
        """,
        pattern_id,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Pattern not found or no evidence")
    return [PatternEvidenceResponse(**dict(r)) for r in rows]


@router.post("/{pattern_id}/confirm", response_model=PatternResponse)
async def confirm_pattern(
    pattern_id: uuid.UUID,
    body: PatternConfirmRequest = PatternConfirmRequest(),
    user_id: uuid.UUID = Depends(get_current_user_id),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    User confirms: "this pattern is me."

    This sets confirmed_at in pattern_visibility, which unlocks the
    hypothesis → active transition. The database trigger enforces that
    this confirmation MUST exist before the status can change.
    """
    # Verify the pattern exists and is a hypothesis
    pattern = await conn.fetchrow(
        "SELECT id, status FROM patterns WHERE id = $1", pattern_id
    )
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    if pattern["status"] != "hypothesis":
        raise HTTPException(
            status_code=409,
            detail=f"Pattern is '{pattern['status']}', not 'hypothesis'. Only hypotheses can be confirmed."
        )

    # Record the confirmation
    now = datetime.now(timezone.utc)
    await conn.execute(
        """
        UPDATE pattern_visibility
        SET first_seen_at = COALESCE(first_seen_at, $2),
            confirmed_at = $2
        WHERE pattern_id = $1 AND user_id = $3
        """,
        pattern_id,
        now,
        user_id,
    )

    # Now promote to active — the trigger will verify confirmed_at exists
    row = await conn.fetchrow(
        """
        UPDATE patterns SET status = 'active'
        WHERE id = $1
        RETURNING id, user_id, insight, category, confidence, domains,
                  temporal_trend, status, evidence_count, temporal_spread,
                  specificity, is_tension, first_seen, last_evidence, created_at
        """,
        pattern_id,
    )
    return PatternResponse(**dict(row))


@router.post("/{pattern_id}/reject", response_model=PatternResponse)
async def reject_pattern(
    pattern_id: uuid.UUID,
    body: PatternRejectRequest,
    user_id: uuid.UUID = Depends(get_current_user_id),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    User rejects: "this isn't me."

    The rejection is recorded as a hard negative. The reason is fed back
    into the extraction prompt to prevent rediscovering the same pattern.
    Rejection rate is tracked as a quality circuit breaker.
    """
    pattern = await conn.fetchrow(
        "SELECT id, status FROM patterns WHERE id = $1", pattern_id
    )
    if not pattern:
        raise HTTPException(status_code=404, detail="Pattern not found")
    if pattern["status"] not in ("hypothesis", "active"):
        raise HTTPException(
            status_code=409,
            detail=f"Pattern is '{pattern['status']}' — only hypothesis or active patterns can be rejected."
        )

    # Record the rejection
    await conn.execute(
        """
        INSERT INTO pattern_rejections (pattern_id, user_id, reason)
        VALUES ($1, $2, $3)
        """,
        pattern_id,
        user_id,
        body.reason,
    )

    # Update pattern status
    row = await conn.fetchrow(
        """
        UPDATE patterns SET status = 'rejected'
        WHERE id = $1
        RETURNING id, user_id, insight, category, confidence, domains,
                  temporal_trend, status, evidence_count, temporal_spread,
                  specificity, is_tension, first_seen, last_evidence, created_at
        """,
        pattern_id,
    )
    return PatternResponse(**dict(row))


@router.post("/extract", response_model=ExtractionResult)
async def trigger_extraction(
    user_id: uuid.UUID = Depends(get_current_user_id),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Trigger pattern extraction for the authenticated user.

    In production this would be a background job (Taskiq).
    In the vertical slice it runs synchronously.
    Checks the rejection-rate circuit breaker before proceeding.
    """
    return await run_extraction(conn, user_id)


@router.get("/validation-status", response_model=ValidationStatus)
async def validation_status(
    user_id: uuid.UUID = Depends(get_current_user_id),
    conn: asyncpg.Connection = Depends(get_db),
):
    """Check the rejection-rate circuit breaker status."""
    return await check_rejection_rate(conn, user_id)
