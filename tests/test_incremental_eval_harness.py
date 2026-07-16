"""
Prove the INCREMENTAL eval instrument works before pointing it at a model.

The straddle corpus plants a slow-burn pattern (Sunday-evening dread)
whose evidence never shows 3+ times inside any single window. A pipeline
that only looks within the window can never catch it — that silent
cross-window loss is the characteristic failure mode of incremental
extraction (spec §4). These tests feed the REAL incremental pipeline
(watermark, digest, candidate storage, evidence links, real promotion
triggers) mock extractors with known behavior:

  - goldfish  → within-window-only, never uses the digest → the straddle
                eval must FAIL for it. If it doesn't, the harness is broken.
  - ledger    → proposes the weak signal as a 1-entry candidate, then
                reinforces it by digest pattern_id in later windows → must
                reach hypothesis via the REAL evidence-floor trigger.
  - watermark → runs recorded, watermarks strictly increase, and a run
                with no new entries makes NO LLM call and stores no run row.
  - reinforce validation → hallucinated pattern/entry ids are skipped,
                counted, and never become pattern_evidence rows.

No LLM key needed — these run in CI.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest

import app.services.incremental as incremental
from app.services.incremental import run_incremental_extraction
from evals.replay import replay_incremental, score_straddle
from evals.straddle import (
    STRADDLE_CORPUS,
    STRADDLE_PLANTED_INDICES,
    WINDOW_SIZE,
)
from tests.conftest import (
    create_test_entry,
    create_test_pattern,
    create_test_user,
)


LEDGER_INSIGHT = (
    "We noticed a creeping sense of dread on Sunday evenings about the week "
    "ahead — a heaviness that settles in as the weekend ends and seems to "
    "ease once the week actually starts."
)


def _pattern(insight: str, entry_ids: list[int], confidence: float = 0.15) -> dict:
    return {
        "insight": insight,
        "category": "emotional",
        "confidence": confidence,
        "evidence_entry_ids": entry_ids,
        "contradiction_entry_ids": [],
        "domains": ["emotional"],
        "specificity": "contextual",
    }


def _planted_in_batch(batch: list[tuple[int, int]]) -> list[int]:
    """DB entry ids of planted entries among this window's new entries."""
    return [db_id for idx, db_id in batch if idx in STRADDLE_PLANTED_INDICES]


def _digest_pattern_id(prompt: str, insight: str) -> str | None:
    """Find `insight` in the prompt's digest section and pull its uuid —
    exactly what a real model must do to emit a reinforce triple."""
    for line in prompt.splitlines():
        if insight in line:
            m = re.search(r"id=([0-9a-f-]{36})", line)
            if m:
                return m.group(1)
    return None


async def _replay_with(conn, llm_fn):
    user_id = await create_test_user(conn, email=f"inc-{uuid.uuid4()}@test.com")
    replay = await replay_incremental(
        conn, user_id, STRADDLE_CORPUS, WINDOW_SIZE, llm_fn=llm_fn
    )
    planted_db_ids = {replay.id_map[i] for i in STRADDLE_PLANTED_INDICES}
    return user_id, replay, planted_db_ids


# ── (a) GOLDFISH: within-window-only extractor must FAIL the eval ─────


@pytest.mark.asyncio
async def test_goldfish_extractor_fails_straddle_eval(conn):
    """
    The goldfish only proposes a pattern when >= 3 planted entries appear
    within the current window's new entries, and never reads the digest
    or emits reinforcements. The straddle corpus guarantees no window of
    WINDOW_SIZE consecutive entries carries more than 2 planted entries,
    so the goldfish must come up empty — and the eval must say so. A
    harness that passes the goldfish cannot catch cross-window loss and
    is broken as an instrument.
    """
    proposals = []

    def goldfish(prompt: str, batch: list[tuple[int, int]]) -> dict:
        planted_here = _planted_in_batch(batch)
        if len(planted_here) >= 3:
            proposals.append(planted_here)
            return {
                "discover": [_pattern(LEDGER_INSIGHT, planted_here, confidence=0.3)],
                "reinforce": [],
            }
        return {"discover": [], "reinforce": []}

    _, replay, planted_db_ids = await _replay_with(conn, goldfish)
    score = score_straddle(replay.stored, planted_db_ids)

    # The corpus never gave it 3-in-a-window, so it never proposed anything
    assert proposals == [], (
        "Straddle corpus is broken: a window contained >= 3 planted entries"
    )
    assert not score.detected, score.explain()
    assert all(p.status != "hypothesis" for p in replay.stored)
    assert replay.stored == []


# ── (b) LEDGER: candidates carry the weak signal across windows ───────


@pytest.mark.asyncio
async def test_ledger_extractor_reaches_hypothesis_across_windows(conn):
    """
    The ledger extractor behaves the way the incremental prompt asks a
    real model to behave: on first sighting it proposes the slow-burn
    pattern as a candidate citing just the 1-2 planted entries in the
    window; in later windows it finds the candidate in the digest and
    emits reinforce triples to the new planted entries. The REAL DB
    trigger must promote it to hypothesis once the evidence floor (3
    supports) is crossed — end-to-end proof that candidates work as the
    cross-window weak-signal ledger.
    """

    def ledger(prompt: str, batch: list[tuple[int, int]]) -> dict:
        planted_here = _planted_in_batch(batch)
        pattern_id = _digest_pattern_id(prompt, LEDGER_INSIGHT)
        if pattern_id is None:
            # Not in the digest yet: first sighting → propose as candidate
            if planted_here:
                return {
                    "discover": [_pattern(LEDGER_INSIGHT, planted_here)],
                    "reinforce": [],
                }
            return {"discover": [], "reinforce": []}
        # Already ledgered: reinforce by id from the digest
        return {
            "discover": [],
            "reinforce": [
                {"pattern_id": pattern_id, "entry_id": e, "relation": "supports"}
                for e in planted_here
            ],
        }

    _, replay, planted_db_ids = await _replay_with(conn, ledger)
    score = score_straddle(replay.stored, planted_db_ids)

    assert score.detected, score.explain()
    assert score.best_pattern is not None
    # Promoted by the real evidence-floor trigger, not by any mock shortcut
    assert score.best_pattern.status == "hypothesis", score.explain()
    # >= 3 planted supporting citations, all of them planted
    planted_citations = set(score.best_pattern.supporting_entry_ids) & planted_db_ids
    assert len(planted_citations) >= 3
    assert score.evidence_precision == 1.0
    # All five planted entries were eventually accumulated across windows
    assert len(planted_citations) == 5
    # And at least one run reported a promotion via the reinforce path
    assert any(r.promoted_to_hypothesis > 0 for r in replay.run_results)


# ── (c) WATERMARK: runs recorded, no-op runs make no LLM call ─────────


@pytest.mark.asyncio
async def test_watermark_advances_and_noop_run_skips_llm(conn):
    def quiet(prompt: str, batch: list[tuple[int, int]]) -> dict:
        return {"discover": [], "reinforce": []}

    user_id, replay, _ = await _replay_with(conn, quiet)

    rows = await conn.fetch(
        """
        SELECT entries_through, kind, prompt_version, window_size
        FROM extraction_runs WHERE user_id = $1
        """,
        user_id,
    )
    # One run row per window
    assert len(rows) == len(STRADDLE_CORPUS) // WINDOW_SIZE
    assert all(r["kind"] == "discover" for r in rows)
    assert all(r["prompt_version"] == "inc-v1" for r in rows)
    assert all(r["window_size"] == WINDOW_SIZE for r in rows)

    # Watermarks strictly increase and each equals its window's max entry id
    watermarks = sorted(r["entries_through"] for r in rows)
    assert len(set(watermarks)) == len(watermarks), "watermarks must be distinct"
    expected = sorted(
        replay.id_map[start + WINDOW_SIZE - 1]
        for start in range(0, len(STRADDLE_CORPUS), WINDOW_SIZE)
    )
    assert watermarks == expected

    # No new entries → NO LLM call and no new run row
    async def must_not_be_called(prompt: str) -> dict:
        raise AssertionError("LLM was called despite zero new entries")

    original = incremental._call_llm
    incremental._call_llm = must_not_be_called
    try:
        result = await run_incremental_extraction(
            conn, user_id, window_size=WINDOW_SIZE
        )
    finally:
        incremental._call_llm = original

    assert result.patterns_discovered == 0
    assert "no new entries" in result.message.lower()
    count_after = await conn.fetchval(
        "SELECT COUNT(*) FROM extraction_runs WHERE user_id = $1", user_id
    )
    assert count_after == len(rows), "an early-returned run must not store a run row"


# ── (d) REINFORCE VALIDATION: hallucinated ids are skipped, counted ───


@pytest.mark.asyncio
async def test_reinforce_rejects_foreign_pattern_and_out_of_window_entry(
    conn, monkeypatch
):
    user_a = await create_test_user(conn, email=f"inc-a-{uuid.uuid4()}@test.com")
    user_b = await create_test_user(conn, email=f"inc-b-{uuid.uuid4()}@test.com")

    pattern_a = await create_test_pattern(conn, user_a, insight="We noticed pattern A")
    pattern_b = await create_test_pattern(conn, user_b, insight="We noticed pattern B")

    entry_a1 = await create_test_entry(conn, user_a, "A quiet morning, tea and lists.")
    await create_test_entry(conn, user_a, "Second entry, unremarkable day.")
    entry_b = await create_test_entry(conn, user_b, "Someone else's diary entry.")

    async def hallucinating(prompt: str) -> dict:
        return {
            "discover": [],
            "reinforce": [
                # another user's pattern — must be skipped
                {"pattern_id": str(pattern_b), "entry_id": entry_a1, "relation": "supports"},
                # our pattern, but an entry outside our window — must be skipped
                {"pattern_id": str(pattern_a), "entry_id": entry_b, "relation": "supports"},
                # valid — must land
                {"pattern_id": str(pattern_a), "entry_id": entry_a1, "relation": "supports"},
            ],
        }

    monkeypatch.setattr(incremental, "_call_llm", hallucinating)
    result = await run_incremental_extraction(conn, user_a)
    assert not result.circuit_breaker_tripped

    # Skips are counted in the run's stats
    stats_raw = await conn.fetchval(
        "SELECT stats FROM extraction_runs WHERE user_id = $1", user_a
    )
    stats = json.loads(stats_raw)
    assert stats["skipped_invalid"] == 2
    assert stats["reinforced"] == 1

    # No evidence rows were created for the invalid triples
    foreign = await conn.fetchval(
        "SELECT COUNT(*) FROM pattern_evidence WHERE pattern_id = $1",
        pattern_b,
    )
    assert foreign == 0
    out_of_window = await conn.fetchval(
        "SELECT COUNT(*) FROM pattern_evidence WHERE pattern_id = $1 AND entry_id = $2",
        pattern_a,
        entry_b,
    )
    assert out_of_window == 0

    # The valid triple landed
    valid = await conn.fetchval(
        "SELECT COUNT(*) FROM pattern_evidence WHERE pattern_id = $1 AND entry_id = $2",
        pattern_a,
        entry_a1,
    )
    assert valid == 1
