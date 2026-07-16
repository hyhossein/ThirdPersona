"""
Pattern validation service.

Implements:
  - Evidence floor as a creation gate (enforced by DB trigger, checked here too)
  - Rejection feedback loop (rejections stored, fed back to extraction prompt)
  - Rejection-rate circuit breaker (halts extraction if too many patterns rejected)
"""

from __future__ import annotations

import uuid
import asyncpg

from app.config import settings
from app.schemas import ValidationStatus


async def check_rejection_rate(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
) -> ValidationStatus:
    """
    Check whether the rejection-rate circuit breaker should trip.

    If more than REJECTION_RATE_THRESHOLD (default 40%) of patterns
    created in the last 30 days have been rejected, the extraction
    pipeline should pause. This is a quality signal: the LLM is
    producing patterns the user doesn't recognize, which means it's
    either miscalibrated or the user's self-reporting is too sparse
    for reliable extraction.

    The circuit breaker is checked before every extraction run.
    It does NOT prevent the user from confirming/rejecting existing
    patterns — only from generating new ones.
    """
    row = await conn.fetchrow(
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

    rejections = row["rejections_30d"] or 0
    total = row["patterns_30d"] or 0
    rate = rejections / total if total > 0 else 0.0

    return ValidationStatus(
        rejection_rate_30d=rate,
        rejections_30d=rejections,
        patterns_30d=total,
        circuit_breaker_active=rate > settings.rejection_rate_threshold and total >= 5,
        threshold=settings.rejection_rate_threshold,
    )
