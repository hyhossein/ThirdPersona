"""
Incremental replay harness (spec §4, step 2).

Feeds a corpus into the database one window at a time and runs the REAL
incremental pipeline (app.services.incremental.run_incremental_extraction
— watermark, digest, candidate storage, evidence links, promotion
triggers) after each window. Scoring reads back what actually landed in
the database, exactly like the full-corpus harness: the eval cannot be
passed by producing plausible text that never survives the storage path.

The mock injection point is incremental._call_llm. A test-provided
`llm_fn` is called as:

    llm_fn(prompt: str, batch: list[tuple[int, int]]) -> dict

where `batch` is the list of (corpus_index, db_entry_id) pairs seeded in
the CURRENT window — the "new entries" of this run. Mocks get to reason
in corpus space (which entries are planted) while the pipeline only ever
sees database rows; anything a mock wants from the digest (candidate
pattern ids, prior insights) it must parse out of the prompt, the same
way a real model would. The return value must be the incremental output
object: {"discover": [...], "reinforce": [...]}.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable

import asyncpg

import app.services.incremental as incremental
from app.schemas import ExtractionResult
from evals.corpus import CorpusEntry
from evals.harness import (
    PlantedScore,
    StoredPattern,
    fetch_stored_patterns,
    score_planted,
    seed_corpus,
)
from evals.straddle import STRADDLE_DREAD_SIGNAL, STRADDLE_SUNDAY_SIGNAL


@dataclass
class ReplayResult:
    stored: list[StoredPattern]           # final DB state — the unit of scoring
    id_map: dict[int, int]                # corpus index -> DB entry id
    run_results: list[ExtractionResult] = field(default_factory=list)


async def replay_incremental(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    corpus: list[CorpusEntry],
    window_size: int,
    llm_fn: Callable[[str, list[tuple[int, int]]], dict] | None = None,
) -> ReplayResult:
    """
    Seed `corpus` one window_size batch at a time (chronological order) and
    run the real incremental pipeline after each batch. Returns the final
    stored patterns plus the corpus-index -> entry-id map.

    If llm_fn is given, incremental._call_llm is patched for the duration
    of the replay (and restored afterwards) so no real model is called.
    """
    id_map: dict[int, int] = {}
    run_results: list[ExtractionResult] = []
    original_call_llm = incremental._call_llm

    try:
        for start in range(0, len(corpus), window_size):
            batch_entries = corpus[start : start + window_size]
            batch_map = await seed_corpus(conn, user_id, batch_entries)
            # seed_corpus keys are batch-local; re-key to corpus indices
            batch = [(start + j, db_id) for j, db_id in sorted(batch_map.items())]
            id_map.update(dict(batch))

            if llm_fn is not None:
                current_batch = batch

                async def _patched(prompt: str, _batch=current_batch) -> dict:
                    return llm_fn(prompt, _batch)

                incremental._call_llm = _patched

            result = await incremental.run_incremental_extraction(
                conn, user_id, window_size=window_size
            )
            run_results.append(result)
    finally:
        incremental._call_llm = original_call_llm

    stored = await fetch_stored_patterns(conn, user_id)
    return ReplayResult(stored=stored, id_map=id_map, run_results=run_results)


STRADDLE_SIGNALS: tuple[str, ...] = (STRADDLE_SUNDAY_SIGNAL, STRADDLE_DREAD_SIGNAL)


def score_straddle(
    stored: list[StoredPattern], planted_db_ids: set[int]
) -> PlantedScore:
    """
    Score the straddle corpus: same bars as the full-corpus planted score
    (>= 3 supporting citations into the planted set, evidence precision
    >= 0.6, insight matches BOTH signal families) with the straddle
    pattern's signal regexes.
    """
    return score_planted(stored, planted_db_ids, signals=STRADDLE_SIGNALS)
