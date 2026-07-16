"""
LIVE extraction ground-truth eval — requires ANTHROPIC_API_KEY.

This is the test that speaks to whether the product helps people or
confidently lies to them. It runs the real extraction pipeline with the
real model against corpora with known ground truth:

  PLANTED: the pipeline must surface the embedded authority-anxiety
  pattern, citing >= 3 of the 5 planted entries, with majority-planted
  evidence and an insight that carries the signal.

  CONTROL: no pattern may reach the evidence floor — the control corpus
  is constructed so no theme occurs 3+ times, so any pattern with 3+
  supporting citations is fabricated by construction.

Skipped without a key (this cannot be tested with mocks — the mocked
version lives in test_extraction_eval_harness.py and proves the
instrument, not the model). Run:

    ANTHROPIC_API_KEY=sk-... python -m pytest tests/test_extraction_ground_truth_live.py -v -s

A single run is a sample, not a verdict — model output varies. For a
stable read, use evals/run_live_eval.py --runs 5 and look at the rates.
"""

from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.services.extraction import run_extraction
from evals.corpus import PLANTED_CORPUS, CONTROL_CORPUS, PLANTED_INDICES
from evals.harness import (
    seed_corpus,
    fetch_stored_patterns,
    score_planted,
    score_control,
)
from tests.conftest import create_test_user

requires_llm = pytest.mark.skipif(
    not settings.anthropic_api_key,
    reason="ANTHROPIC_API_KEY not set — live ground-truth eval skipped. "
    "Extraction quality remains UNPROVEN until this runs.",
)


@requires_llm
@pytest.mark.asyncio
async def test_live_planted_pattern_is_surfaced_with_correct_evidence(conn):
    user_id = await create_test_user(conn, email=f"live-{uuid.uuid4()}@test.com")
    id_map = await seed_corpus(conn, user_id, PLANTED_CORPUS)

    await run_extraction(conn, user_id)

    stored = await fetch_stored_patterns(conn, user_id)
    planted_ids = {id_map[i] for i in PLANTED_INDICES}
    score = score_planted(stored, planted_ids)

    print("\n" + score.explain())
    assert score.detected, (
        "The pipeline failed to surface the planted authority-anxiety "
        "pattern with correct evidence citations.\n" + score.explain()
    )


@requires_llm
@pytest.mark.xfail(
    reason="Control v1 premise invalidated by adjudication (2026-07-16): "
    "every live 'fabrication' was a TRUE regularity of the single-author "
    "text — authorial voice is itself a pattern, so 'nothing reaches the "
    "floor' cannot certify honesty. See the adjudication log in "
    "evals/corpus.py. Superseded by the targeted absence probe "
    "(test_extraction_absence_probe_live.py), which passed 3/3.",
    strict=False,
)
@pytest.mark.asyncio
async def test_live_control_corpus_produces_no_fabricated_pattern(conn):
    user_id = await create_test_user(conn, email=f"livec-{uuid.uuid4()}@test.com")
    await seed_corpus(conn, user_id, CONTROL_CORPUS)

    await run_extraction(conn, user_id)

    stored = await fetch_stored_patterns(conn, user_id)
    score = score_control(stored)

    print("\n" + score.explain())
    assert score.clean, (
        "The pipeline invented a pattern from noise — it reached the "
        "evidence floor on a corpus where no theme occurs 3+ times.\n"
        + score.explain()
    )
