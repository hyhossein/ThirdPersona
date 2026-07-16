"""Pydantic schemas for API request/response models."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal
import uuid


# ── Entries ──────────────────────────────────────────────────────────

class EntryCreate(BaseModel):
    text_content: str = Field(..., min_length=1, max_length=50_000)
    source_type: Literal["manual", "voice", "ai_import", "photo", "location"] = "manual"


class EntryResponse(BaseModel):
    id: int
    user_id: uuid.UUID
    text_content: str | None
    source_type: str
    mood_energy: int | None
    mood_openness: int | None
    mood_tension: int | None
    domains: list[str] | None
    richness_score: float | None
    created_at: datetime


# ── Patterns ─────────────────────────────────────────────────────────

class PatternResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    insight: str
    category: str
    confidence: float
    domains: list[str]
    temporal_trend: str
    status: str
    evidence_count: int
    temporal_spread: int
    specificity: str
    is_tension: bool
    first_seen: datetime
    last_evidence: datetime | None
    created_at: datetime


class PatternEvidenceResponse(BaseModel):
    entry_id: int
    relation: str
    weight: float
    entry_text: str | None  # included for traceability
    created_at: datetime


class PatternConfirmRequest(BaseModel):
    """User says: this pattern is me."""
    pass  # No body needed — the act of calling the endpoint IS the confirmation


class PatternRejectRequest(BaseModel):
    """User says: this isn't me."""
    reason: str | None = Field(
        None,
        description="Why this pattern doesn't fit. Fed back as a hard negative."
    )


# ── Extraction ───────────────────────────────────────────────────────

class ExtractedPattern(BaseModel):
    """One pattern extracted by the LLM."""
    insight: str
    category: Literal[
        "relational", "self", "conflict", "social",
        "intellectual", "emotional", "energy", "values", "growth"
    ]
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_entry_ids: list[int]
    contradiction_entry_ids: list[int] = []
    domains: list[str]
    specificity: Literal["general", "contextual", "episodic"] = "general"
    is_tension: bool = False
    tension_with: str | None = None
    context_conditions: str | None = None


class ExtractionResult(BaseModel):
    """Response from the extraction pipeline."""
    patterns_discovered: int
    candidates_created: int
    promoted_to_hypothesis: int
    circuit_breaker_tripped: bool = False
    message: str


# ── Validation ───────────────────────────────────────────────────────

class ValidationStatus(BaseModel):
    rejection_rate_30d: float
    rejections_30d: int
    patterns_30d: int
    circuit_breaker_active: bool
    threshold: float
