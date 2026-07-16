"""
Pattern extraction service.

Calls the LLM to discover behavioral patterns from accumulated diary entries.
Produces candidates that auto-promote to hypotheses when the evidence floor is met.

The extraction prompt:
  - Uses "we noticed..." language (hypotheses, not findings)
  - Includes previously rejected patterns as hard negatives
  - Returns structured output validated by Pydantic
  - Confidence reflects evidence volume, not LLM certainty
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import asyncpg

from app.config import settings
from app.schemas import ExtractedPattern, ExtractionResult
from app.services.validation import check_rejection_rate

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """\
You are a pattern discovery engine for ThirdPersona, a personal observability tool.

Your job: analyze diary entries and identify behavioral patterns — recurring \
tendencies, emotional rhythms, relational dynamics, and value expressions \
that emerge across multiple entries.

## Rules

1. **Hypotheses, not findings.** Every pattern you surface is a hypothesis. \
Frame insights as observations: "We noticed..." or "There seems to be a \
pattern of..." — NEVER "You are..." or "You always..."

2. **Evidence-grounded.** Every pattern MUST cite specific entry IDs as \
evidence. A pattern without evidence does not exist. Minimum 2 supporting \
entries to propose a pattern.

3. **Confidence from evidence volume, not your certainty.** Confidence \
scores reflect how much independent evidence supports this pattern, not how \
sure you are. 3 entries = low confidence (~0.3). 5 entries across weeks = \
moderate (~0.5). 10+ entries spanning months = high (~0.8). Your internal \
certainty is uncalibrated in this domain and must not inflate the score.

4. **Contradictions are data.** If entries contradict each other on the same \
theme, that's a tension pair, not noise. "We noticed you tend to withdraw \
during conflict with some people but engage directly with others" is a valid \
finding. Do not force coherence.

5. **Previously rejected patterns.** The user has rejected the patterns \
listed below. Do NOT rediscover them in the same or similar form. They are \
hard negatives — the user explicitly said "this isn't me." If you find \
yourself arriving at something similar, skip it.

6. **Categories.** Each pattern belongs to exactly one: relational, self, \
conflict, social, intellectual, emotional, energy, values, growth.

7. **Specificity assessment.** Rate each pattern:
   - "general": describes a recurring tendency across many contexts
   - "contextual": describes behavior in a specific type of context
   - "episodic": traces to a narrow set of specific events

## Previously Rejected Patterns (do not rediscover)
{rejected_patterns}

## Diary Entries
{entries}

## Output Format
Return a JSON array of discovered patterns. Each element:
{{
  "insight": "We noticed that ...",
  "category": "one of the 9 categories",
  "confidence": 0.0 to 1.0,
  "evidence_entry_ids": [list of entry IDs that support this],
  "contradiction_entry_ids": [list of entry IDs that contradict this],
  "domains": ["which identity domains this spans"],
  "specificity": "general|contextual|episodic",
  "is_tension": false,
  "tension_with": "description of the contradicting tendency, if is_tension=true",
  "context_conditions": "when does this pattern apply, if contextual"
}}

Be selective. Propose only patterns with genuine evidence across multiple \
entries. A single entry is an event, not a pattern. Two entries might be \
coincidence. Three or more entries spanning different days suggest something \
real. Quality over quantity.\
"""


async def _get_entries(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[dict]:
    """Fetch all entries for this user (for the vertical slice, no pagination)."""
    rows = await conn.fetch(
        """
        SELECT id, text_content, source_type, mood_energy, mood_openness,
               mood_tension, domains, created_at
        FROM entries
        WHERE user_id = $1
        ORDER BY created_at ASC
        """,
        user_id,
    )
    return [
        {
            "id": r["id"],
            "text": r["text_content"] or "",
            "source": r["source_type"],
            "date": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def _get_rejections(conn: asyncpg.Connection, user_id: uuid.UUID) -> list[dict]:
    """Fetch rejected patterns with reasons (hard negatives for the prompt)."""
    rows = await conn.fetch(
        """
        SELECT p.insight, p.category, pr.reason
        FROM pattern_rejections pr
        JOIN patterns p ON p.id = pr.pattern_id
        WHERE pr.user_id = $1
        ORDER BY pr.rejected_at DESC
        """,
        user_id,
    )
    return [dict(r) for r in rows]


async def _get_existing_pattern_insights(
    conn: asyncpg.Connection, user_id: uuid.UUID
) -> set[str]:
    """Get insights of existing non-rejected patterns to avoid duplicates."""
    rows = await conn.fetch(
        """
        SELECT insight FROM patterns
        WHERE user_id = $1 AND status NOT IN ('rejected', 'archived')
        """,
        user_id,
    )
    return {r["insight"] for r in rows}


async def _call_llm(prompt: str) -> list[dict[str, Any]]:
    """
    Call the Anthropic API for pattern extraction.
    Returns parsed JSON array of patterns.

    Falls back to empty list if API key is not configured
    (allows running tests without an API key).
    """
    if not settings.anthropic_api_key:
        logger.warning("No ANTHROPIC_API_KEY configured — skipping LLM extraction")
        return []

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=settings.extraction_model,
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        # Extract JSON from the response (handle markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        return json.loads(text.strip())

    except Exception as e:
        logger.error(f"LLM extraction failed: {e}")
        return []


async def _store_candidate(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    pattern: ExtractedPattern,
) -> uuid.UUID | None:
    """
    Store a candidate pattern and its evidence links.
    The evidence insertion trigger auto-promotes to hypothesis
    if the evidence floor is met.
    """
    # Insert the pattern as a candidate
    row = await conn.fetchrow(
        """
        INSERT INTO patterns (
            user_id, insight, category, confidence, domains,
            specificity, is_tension, context_conditions, status
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'candidate')
        RETURNING id
        """,
        user_id,
        pattern.insight,
        pattern.category,
        pattern.confidence,
        pattern.domains,
        pattern.specificity,
        pattern.is_tension,
        json.dumps(pattern.context_conditions) if pattern.context_conditions else None,
    )
    pattern_id = row["id"]

    # Link supporting evidence — each INSERT fires the promotion trigger
    for entry_id in pattern.evidence_entry_ids:
        try:
            await conn.execute(
                """
                INSERT INTO pattern_evidence (pattern_id, entry_id, user_id, relation, weight)
                VALUES ($1, $2, $3, 'supports', 1.0)
                ON CONFLICT DO NOTHING
                """,
                pattern_id,
                entry_id,
                user_id,
            )
        except asyncpg.ForeignKeyViolationError:
            logger.warning(f"Entry {entry_id} not found — skipping evidence link")

    # Link contradicting evidence
    for entry_id in pattern.contradiction_entry_ids:
        try:
            await conn.execute(
                """
                INSERT INTO pattern_evidence (pattern_id, entry_id, user_id, relation, weight)
                VALUES ($1, $2, $3, 'contradicts', 0.5)
                ON CONFLICT DO NOTHING
                """,
                pattern_id,
                entry_id,
                user_id,
            )
        except asyncpg.ForeignKeyViolationError:
            pass

    return pattern_id


async def run_extraction(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
) -> ExtractionResult:
    """
    Run the full extraction pipeline:
    1. Check rejection-rate circuit breaker
    2. Gather entries and rejections
    3. Call LLM
    4. Store candidates (triggers auto-promote to hypothesis)
    """
    # 1. Circuit breaker check
    validation = await check_rejection_rate(conn, user_id)
    if validation.circuit_breaker_active:
        return ExtractionResult(
            patterns_discovered=0,
            candidates_created=0,
            promoted_to_hypothesis=0,
            circuit_breaker_tripped=True,
            message=(
                f"Extraction paused: {validation.rejection_rate_30d:.0%} of recent "
                f"patterns were rejected (threshold: {validation.threshold:.0%}). "
                f"The system needs recalibration before discovering more patterns."
            ),
        )

    # 2. Gather data
    entries = await _get_entries(conn, user_id)
    if len(entries) < 3:
        return ExtractionResult(
            patterns_discovered=0,
            candidates_created=0,
            promoted_to_hypothesis=0,
            message="Need at least 3 entries before pattern extraction runs.",
        )

    rejections = await _get_rejections(conn, user_id)
    existing_insights = await _get_existing_pattern_insights(conn, user_id)

    # 3. Build prompt and call LLM
    rejected_text = "None yet." if not rejections else "\n".join(
        f"- [{r['category']}] {r['insight']} (reason: {r.get('reason', 'none given')})"
        for r in rejections
    )
    entries_text = "\n\n".join(
        f"[Entry {e['id']}] ({e['date']}, {e['source']})\n{e['text']}"
        for e in entries
    )

    prompt = EXTRACTION_PROMPT.format(
        rejected_patterns=rejected_text,
        entries=entries_text,
    )

    raw_patterns = await _call_llm(prompt)

    # 4. Validate and store
    candidates_created = 0
    promoted = 0

    for raw in raw_patterns:
        try:
            pattern = ExtractedPattern(**raw)
        except Exception as e:
            logger.warning(f"Invalid pattern from LLM: {e}")
            continue

        # Skip if too similar to existing pattern
        if pattern.insight in existing_insights:
            continue

        # Store candidate — trigger handles promotion
        pattern_id = await _store_candidate(conn, user_id, pattern)
        if pattern_id:
            candidates_created += 1
            # Check if it was promoted
            status = await conn.fetchval(
                "SELECT status FROM patterns WHERE id = $1", pattern_id
            )
            if status == "hypothesis":
                promoted += 1

    return ExtractionResult(
        patterns_discovered=len(raw_patterns),
        candidates_created=candidates_created,
        promoted_to_hypothesis=promoted,
        message=f"Extracted {len(raw_patterns)} patterns. {candidates_created} stored as candidates, {promoted} auto-promoted to hypothesis.",
    )
