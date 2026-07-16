"""
Incremental pattern extraction (spec §3 — build-order steps 2–3).

Instead of re-reading the full corpus, each run reads:
  - the entries since the last watermark (extraction_runs.entries_through),
  - a small overlap tail for local continuity,
  - a deterministic digest of the user's current pattern state.

Two operations in ONE model call (spec §3.4):
  - discover:  new candidate patterns in the window (allowed on as few
    as 1–2 supporting entries — candidates are invisible to the user and
    the evidence floor still gates promotion; this is the weak-signal
    ledger that carries slow-burn patterns across windows).
  - reinforce: (pattern_id, entry_id, relation) triples linking window
    entries to digest patterns — including candidates. Stored as
    pattern_evidence; the existing promotion trigger does the rest.

NOT wired into any API endpoint. The /patterns/extract endpoint stays on
full-corpus extraction until the incremental live eval passes its bars
(spec §4). This module is invoked only by tests and the eval harness.

Trust architecture unchanged: same circuit breaker, same candidate
storage path, same triggers, same RLS. The model reads differently;
the database enforces identically.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import asyncpg

from app.config import settings
from app.schemas import ExtractedPattern, ExtractionResult
from app.services.digest import build_pattern_digest
from app.services.extraction import _store_candidate
from app.services.validation import check_rejection_rate

logger = logging.getLogger(__name__)

PROMPT_VERSION = "inc-v1"
OVERLAP_TAIL = 10  # entries at/below the watermark re-shown for continuity


INCREMENTAL_PROMPT = """\
You are a pattern discovery engine for ThirdPersona, a personal observability tool.

You are running in INCREMENTAL mode: you see only the newest diary entries
(plus a short overlap tail), together with a digest of every pattern the
system already tracks for this user. You do NOT see the full history — the
digest is your memory.

## Rules

1. **Hypotheses, not findings.** Every pattern you surface is a hypothesis. \
Frame insights as observations: "We noticed..." or "There seems to be a \
pattern of..." — NEVER "You are..." or "You always..."

2. **Evidence-grounded.** Every discovered pattern MUST cite specific entry \
IDs from the window below. A pattern without evidence does not exist. \
Because you only see a small window, you MAY propose a candidate on as \
little as 1–2 supporting entries — candidates are invisible to the user \
and only promote once enough evidence accumulates across runs. Weak but \
genuine signals are worth ledgering; noise is not.

3. **Reinforce before you rediscover.** If a window entry supports or \
contradicts a pattern already in the digest — including candidates — emit \
a reinforcement triple referencing that pattern's id. Do NOT re-propose a \
digest pattern as a new discovery.

4. **Confidence from evidence volume, not your certainty.** 1–2 entries = \
very low (~0.1–0.2). 3 entries = low (~0.3). 5 entries across weeks = \
moderate (~0.5). Your internal certainty is uncalibrated in this domain \
and must not inflate the score.

5. **Contradictions are data.** If window entries contradict a digest \
pattern, emit a "contradicts" reinforcement — do not force coherence.

6. **Previously rejected patterns.** The digest lists patterns the user \
rejected. They are hard negatives — the user explicitly said "this isn't \
me." Do NOT rediscover them in the same or similar form.

7. **Categories.** Each pattern belongs to exactly one: relational, self, \
conflict, social, intellectual, emotional, energy, values, growth.

8. **Specificity assessment.** Rate each discovered pattern: "general" \
(recurring tendency across contexts), "contextual" (specific type of \
context), or "episodic" (narrow set of specific events).

## Pattern Digest (the system's current state for this user)
{digest}

## Diary Entries (current window — cite ONLY these entry IDs)
{entries}

## Output Format
Return ONE JSON object with exactly two keys:
{{
  "discover": [
    {{
      "insight": "We noticed that ...",
      "category": "one of the 9 categories",
      "confidence": 0.0 to 1.0,
      "evidence_entry_ids": [entry IDs from the window that support this],
      "contradiction_entry_ids": [entry IDs from the window that contradict this],
      "domains": ["which identity domains this spans"],
      "specificity": "general|contextual|episodic",
      "is_tension": false,
      "tension_with": "description of the contradicting tendency, if is_tension=true",
      "context_conditions": "when does this pattern apply, if contextual"
    }}
  ],
  "reinforce": [
    {{
      "pattern_id": "<uuid copied exactly from a digest line>",
      "entry_id": <entry ID from the window>,
      "relation": "supports" or "contradicts"
    }}
  ]
}}

Be selective in "discover" (new signals only), generous and precise in \
"reinforce" (every genuine link between a window entry and a digest \
pattern). Either list may be empty.\
"""


async def _call_llm(prompt: str) -> dict[str, Any]:
    """
    Call the Anthropic API for incremental extraction.
    Returns the parsed JSON object: {"discover": [...], "reinforce": [...]}.

    Falls back to an empty result if API key is not configured
    (allows running tests without an API key). Module-level so tests
    and the replay harness can monkeypatch it.
    """
    if not settings.anthropic_api_key:
        logger.warning("No ANTHROPIC_API_KEY configured — skipping LLM extraction")
        return {"discover": [], "reinforce": []}

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text

        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]

        parsed = json.loads(text.strip())
        if not isinstance(parsed, dict):
            logger.error("Incremental LLM output was not a JSON object")
            return {"discover": [], "reinforce": []}
        return parsed

    except Exception as e:
        logger.error(f"Incremental LLM extraction failed: {e}")
        return {"discover": [], "reinforce": []}


async def _get_watermark(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    """Highest entry id any previous run has covered (0 if none)."""
    value = await conn.fetchval(
        "SELECT MAX(entries_through) FROM extraction_runs WHERE user_id = $1",
        user_id,
    )
    return int(value) if value is not None else 0


async def _get_window(
    conn: asyncpg.Connection, user_id: uuid.UUID, watermark: int
) -> tuple[list[dict], list[dict]]:
    """
    Return (new_entries, overlap_entries), each chronological.

    New: entries with id > watermark. Overlap: up to OVERLAP_TAIL of the
    most recent entries at/below the watermark, for local continuity.
    """
    new_rows = await conn.fetch(
        """
        SELECT id, text_content, source_type, created_at
        FROM entries
        WHERE user_id = $1 AND id > $2
        ORDER BY created_at ASC, id ASC
        """,
        user_id,
        watermark,
    )
    overlap_rows = await conn.fetch(
        """
        SELECT id, text_content, source_type, created_at
        FROM (
            SELECT id, text_content, source_type, created_at
            FROM entries
            WHERE user_id = $1 AND id <= $2
            ORDER BY created_at DESC, id DESC
            LIMIT $3
        ) tail
        ORDER BY created_at ASC, id ASC
        """,
        user_id,
        watermark,
        OVERLAP_TAIL,
    )

    def as_dict(r: asyncpg.Record) -> dict:
        return {
            "id": r["id"],
            "text": r["text_content"] or "",
            "source": r["source_type"],
            "date": r["created_at"].isoformat(),
        }

    return [as_dict(r) for r in new_rows], [as_dict(r) for r in overlap_rows]


async def _store_reinforcement(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    pattern_id: uuid.UUID,
    entry_id: int,
    relation: str,
) -> None:
    """Insert one validated reinforcement as a pattern_evidence row."""
    weight = 1.0 if relation == "supports" else 0.5
    await conn.execute(
        """
        INSERT INTO pattern_evidence (pattern_id, entry_id, user_id, relation, weight)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT DO NOTHING
        """,
        pattern_id,
        entry_id,
        user_id,
        relation,
        weight,
    )


async def run_incremental_extraction(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    window_size: int = 20,
) -> ExtractionResult:
    """
    Run one incremental discover+reinforce pass:

    1. Check the rejection-rate circuit breaker (same gate as full extraction)
    2. Compute the watermark; early-return with NO LLM call if nothing is new
    3. Build the window (new entries + overlap tail) and the pattern digest
    4. One LLM call → {"discover": [...], "reinforce": [...]}
    5. Store discoveries as candidates (existing triggers handle promotion)
       and reinforcements as pattern_evidence (validated, ON CONFLICT DO NOTHING)
    6. Record the run in extraction_runs — same transaction context, so a
       crashed run repeats safely
    """
    # 1. Circuit breaker — exactly the gate full-corpus extraction uses
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

    # 2. Watermark and window
    watermark = await _get_watermark(conn, user_id)
    new_entries, overlap_entries = await _get_window(conn, user_id, watermark)

    if not new_entries:
        return ExtractionResult(
            patterns_discovered=0,
            candidates_created=0,
            promoted_to_hypothesis=0,
            message="No new entries since the last extraction run.",
        )

    window_entries = overlap_entries + new_entries
    window_ids = {e["id"] for e in window_entries}
    entries_through = max(e["id"] for e in new_entries)

    # 3. Digest + prompt
    digest = await build_pattern_digest(conn, user_id)
    entries_text = "\n\n".join(
        f"[Entry {e['id']}] ({e['date']}, {e['source']})\n{e['text']}"
        for e in window_entries
    )
    prompt = INCREMENTAL_PROMPT.format(digest=digest, entries=entries_text)

    # 4. One model call
    raw = await _call_llm(prompt)
    raw_discover = raw.get("discover") or []
    raw_reinforce = raw.get("reinforce") or []

    # 5a. Store discoveries — same path as full-corpus extraction
    existing_insights = {
        r["insight"]
        for r in await conn.fetch(
            """
            SELECT insight FROM patterns
            WHERE user_id = $1 AND status NOT IN ('rejected', 'archived')
            """,
            user_id,
        )
    }

    candidates_created = 0
    promoted = 0
    for raw_pattern in raw_discover:
        try:
            pattern = ExtractedPattern(**raw_pattern)
        except Exception as e:
            logger.warning(f"Invalid pattern from LLM: {e}")
            continue
        if pattern.insight in existing_insights:
            continue
        pattern_id = await _store_candidate(conn, user_id, pattern)
        if pattern_id:
            candidates_created += 1
            status = await conn.fetchval(
                "SELECT status FROM patterns WHERE id = $1", pattern_id
            )
            if status == "hypothesis":
                promoted += 1

    # 5b. Store reinforcements — validated; the model may hallucinate ids
    reinforced = 0
    skipped_invalid = 0
    for triple in raw_reinforce:
        try:
            pattern_id = uuid.UUID(str(triple["pattern_id"]))
            entry_id = int(triple["entry_id"])
            relation = str(triple["relation"])
        except (KeyError, TypeError, ValueError):
            skipped_invalid += 1
            continue

        if relation not in ("supports", "contradicts"):
            skipped_invalid += 1
            continue
        if entry_id not in window_ids:
            skipped_invalid += 1
            continue
        status_before = await conn.fetchval(
            "SELECT status FROM patterns WHERE id = $1 AND user_id = $2",
            pattern_id,
            user_id,
        )
        if status_before is None:
            skipped_invalid += 1
            continue

        await _store_reinforcement(conn, user_id, pattern_id, entry_id, relation)
        reinforced += 1

        # A reinforcement may have promoted a candidate via the trigger
        if status_before == "candidate":
            status_after = await conn.fetchval(
                "SELECT status FROM patterns WHERE id = $1", pattern_id
            )
            if status_after == "hypothesis":
                promoted += 1

    # 6. Record the run — same transaction context as the stores above
    model = "claude-sonnet-4-20250514" if settings.anthropic_api_key else "mock"
    stats = {
        "discovered": len(raw_discover),
        "reinforced": reinforced,
        "skipped_invalid": skipped_invalid,
    }
    await conn.execute(
        """
        INSERT INTO extraction_runs (
            user_id, kind, entries_through, window_size,
            prompt_version, model, stats
        ) VALUES ($1, 'discover', $2, $3, $4, $5, $6)
        """,
        user_id,
        entries_through,
        window_size,
        PROMPT_VERSION,
        model,
        json.dumps(stats),
    )

    return ExtractionResult(
        patterns_discovered=len(raw_discover),
        candidates_created=candidates_created,
        promoted_to_hypothesis=promoted,
        message=(
            f"Incremental run through entry {entries_through}: "
            f"{len(raw_discover)} discovered, {candidates_created} stored as candidates, "
            f"{reinforced} reinforcements applied, {skipped_invalid} invalid skipped, "
            f"{promoted} promoted to hypothesis."
        ),
    )
