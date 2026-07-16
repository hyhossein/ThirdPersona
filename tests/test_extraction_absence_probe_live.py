"""
LIVE targeted absence probe — control v2. Requires ANTHROPIC_API_KEY.

Why this exists: the original control corpus ("no theme occurs 3+ times")
was invalidated by adjudication — across every live run, the model's
control-corpus findings were TRUE regularities of the text (authorial
voice is itself a pattern), never fabrications. See the adjudication log
in evals/corpus.py. That control design cannot certify honesty.

This probe can. The planted corpus is seeded WITH THE 5 PLANTED ENTRIES
REMOVED — nine noise entries, zero authority-anxiety content. If the
pipeline reports the authority-anxiety signal anyway, it is fabricating
the specific thing that is not there. No adjudication ambiguity.
"""

from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.services.extraction import run_extraction
from evals.corpus import PLANTED_CORPUS
from evals.harness import seed_corpus, fetch_stored_patterns, score_absence
from tests.conftest import create_test_user

requires_llm = pytest.mark.skipif(
    not settings.anthropic_api_key,
    reason="ANTHROPIC_API_KEY not set — live absence probe skipped.",
)


@requires_llm
@pytest.mark.asyncio
async def test_live_absent_pattern_is_not_reported(conn):
    user_id = await create_test_user(conn, email=f"absence-{uuid.uuid4()}@test.com")
    noise_only = [e for e in PLANTED_CORPUS if not e.planted]
    await seed_corpus(conn, user_id, noise_only)

    await run_extraction(conn, user_id)

    stored = await fetch_stored_patterns(conn, user_id)
    score = score_absence(stored)

    print("\n" + score.explain())
    assert score.clean, (
        "FABRICATION: the pipeline reported the authority-anxiety pattern "
        "on a corpus containing zero authority-anxiety entries.\n"
        + score.explain()
    )
