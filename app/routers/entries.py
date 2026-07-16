"""Entry ingestion endpoints."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends
import asyncpg

from app.database import get_db, get_current_user_id
from app.schemas import EntryCreate, EntryResponse

router = APIRouter(prefix="/entries", tags=["entries"])


@router.post("", response_model=EntryResponse, status_code=201)
async def create_entry(
    body: EntryCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    Create a diary entry.

    In the vertical slice, mood detection and domain classification
    are deferred to the extraction pipeline. In production, Tier 1
    (Haiku) runs inline here for instant mood bars.
    """
    row = await conn.fetchrow(
        """
        INSERT INTO entries (user_id, text_content, source_type)
        VALUES ($1, $2, $3)
        RETURNING id, user_id, text_content, source_type,
                  mood_energy, mood_openness, mood_tension,
                  domains, richness_score, created_at
        """,
        user_id,
        body.text_content,
        body.source_type,
    )
    return EntryResponse(**dict(row))


@router.get("", response_model=list[EntryResponse])
async def list_entries(
    limit: int = 50,
    offset: int = 0,
    conn: asyncpg.Connection = Depends(get_db),
):
    """
    List the authenticated user's entries (newest first).
    RLS ensures only their own entries are returned.
    """
    rows = await conn.fetch(
        """
        SELECT id, user_id, text_content, source_type,
               mood_energy, mood_openness, mood_tension,
               domains, richness_score, created_at
        FROM entries
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )
    return [EntryResponse(**dict(r)) for r in rows]
