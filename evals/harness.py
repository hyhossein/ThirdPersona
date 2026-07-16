"""
Extraction ground-truth harness.

Runs the REAL extraction pipeline (app.services.extraction.run_extraction,
including candidate storage, evidence links, triggers, and the evidence
floor) against a corpus with known ground truth, then scores what actually
landed in the database. Scoring what's in the DB — not what the LLM said —
means the eval cannot be passed by producing plausible text that never
survives the storage path.

Two scores:

PLANTED (recall): did the pipeline surface the embedded pattern, citing
the planted entries specifically?
  - >= 3 supporting evidence links into the planted entry set
  - evidence precision >= 0.6 (majority of citations are planted entries —
    right answer for the wrong reasons doesn't count)
  - insight text matches BOTH signal families (authority + anxiety) —
    citing the right entries with an unrelated insight doesn't count either.

CONTROL (fabrication): any pattern reaching the evidence floor (>= 3
supports) on the control corpus is a fabrication BY CONSTRUCTION — no
theme occurs 3+ times there. The scorecard carries the offending insights
so a boundary case fails loudly and human-readably.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import asyncpg

from evals.corpus import (
    CorpusEntry,
    AUTHORITY_SIGNAL,
    ANXIETY_SIGNAL,
)

EVIDENCE_FLOOR = 3
EVIDENCE_PRECISION_BAR = 0.6


@dataclass
class StoredPattern:
    pattern_id: uuid.UUID
    insight: str
    status: str
    confidence: float
    supporting_entry_ids: list[int]


@dataclass
class PlantedScore:
    detected: bool
    best_pattern: StoredPattern | None
    planted_hits: int          # citations into the planted set (best pattern)
    evidence_precision: float  # planted / total citations (best pattern)
    insight_matches_signal: bool
    all_patterns: list[StoredPattern] = field(default_factory=list)

    def explain(self) -> str:
        lines = [f"PLANTED corpus: detected={self.detected}"]
        if self.best_pattern:
            lines.append(
                f"  best: '{self.best_pattern.insight[:100]}...' "
                f"(hits={self.planted_hits}, precision={self.evidence_precision:.2f}, "
                f"signal_match={self.insight_matches_signal}, status={self.best_pattern.status})"
            )
        for p in self.all_patterns:
            lines.append(f"  extracted: [{p.status}] {p.insight}")
        return "\n".join(lines)


@dataclass
class ControlScore:
    clean: bool
    fabrications: list[StoredPattern] = field(default_factory=list)
    all_patterns: list[StoredPattern] = field(default_factory=list)

    def explain(self) -> str:
        lines = [f"CONTROL corpus: clean={self.clean}"]
        for p in self.fabrications:
            lines.append(
                f"  FABRICATION ({len(p.supporting_entry_ids)} citations): {p.insight}"
            )
        for p in self.all_patterns:
            lines.append(f"  extracted: [{p.status}] {p.insight}")
        return "\n".join(lines)


async def seed_corpus(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    corpus: list[CorpusEntry],
) -> dict[int, int]:
    """Insert corpus entries; return corpus index -> DB entry id."""
    id_map: dict[int, int] = {}
    for i, entry in enumerate(corpus):
        created = datetime.fromisoformat(entry.date).replace(
            hour=21, minute=30, tzinfo=timezone.utc
        )
        row = await conn.fetchrow(
            """
            INSERT INTO entries (user_id, text_content, created_at)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            user_id,
            entry.text,
            created,
        )
        id_map[i] = row["id"]
    return id_map


async def fetch_stored_patterns(
    conn: asyncpg.Connection, user_id: uuid.UUID
) -> list[StoredPattern]:
    """Read back what the pipeline ACTUALLY stored — the unit of scoring."""
    rows = await conn.fetch(
        """
        SELECT p.id, p.insight, p.status, p.confidence,
               COALESCE(
                   array_agg(pe.entry_id) FILTER (WHERE pe.relation = 'supports'),
                   '{}'
               ) AS supports
        FROM patterns p
        LEFT JOIN pattern_evidence pe ON pe.pattern_id = p.id
        WHERE p.user_id = $1
        GROUP BY p.id, p.insight, p.status, p.confidence
        ORDER BY p.created_at
        """,
        user_id,
    )
    return [
        StoredPattern(
            pattern_id=r["id"],
            insight=r["insight"],
            status=r["status"],
            confidence=r["confidence"],
            supporting_entry_ids=list(r["supports"]),
        )
        for r in rows
    ]


def _matches_signal(insight: str, signals: tuple[str, ...]) -> bool:
    """True iff the insight matches EVERY signal family."""
    low = insight.lower()
    return all(re.search(pattern, low) for pattern in signals)


# Default signal families: the planted authority-anxiety pattern.
DEFAULT_SIGNALS: tuple[str, ...] = (AUTHORITY_SIGNAL, ANXIETY_SIGNAL)


def score_planted(
    stored: list[StoredPattern],
    planted_db_ids: set[int],
    signals: tuple[str, ...] = DEFAULT_SIGNALS,
) -> PlantedScore:
    best: StoredPattern | None = None
    best_hits = 0
    best_precision = 0.0
    best_signal = False
    detected = False

    for p in stored:
        cited = set(p.supporting_entry_ids)
        if not cited:
            continue
        hits = len(cited & planted_db_ids)
        precision = hits / len(cited)
        signal = _matches_signal(p.insight, signals)
        qualifies = (
            hits >= EVIDENCE_FLOOR
            and precision >= EVIDENCE_PRECISION_BAR
            and signal
        )
        if qualifies:
            detected = True
        # Track the strongest attempt for the explanation, qualified or not
        if (hits, precision) > (best_hits, best_precision):
            best, best_hits, best_precision, best_signal = p, hits, precision, signal

    return PlantedScore(
        detected=detected,
        best_pattern=best,
        planted_hits=best_hits,
        evidence_precision=best_precision,
        insight_matches_signal=best_signal,
        all_patterns=stored,
    )


def score_control(stored: list[StoredPattern]) -> ControlScore:
    fabrications = [
        p for p in stored if len(set(p.supporting_entry_ids)) >= EVIDENCE_FLOOR
    ]
    return ControlScore(
        clean=len(fabrications) == 0,
        fabrications=fabrications,
        all_patterns=stored,
    )
