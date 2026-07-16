"""
Prove the eval instrument works before pointing it at a real model.

The ground-truth eval (evals/) is only trustworthy if it can tell an
honest extractor from a dishonest one. These tests feed the REAL pipeline
(run_extraction, real storage, real triggers) mock extractors with known
behavior and assert the harness scores them correctly:

  - honest        → detected on planted corpus, clean on control
  - lying         → confident insight, fabricated citations → caught
  - state-gaming  → right citations, wrong insight → caught
  - lazy          → returns nothing → not detected (and clean on control)

The most important one: the LYING extractor PASSES the lifecycle machinery
(its pattern reaches the evidence floor and is promoted to hypothesis) and
is caught ONLY by the eval. That is the precise sense in which green
lifecycle tests say nothing about extraction truth.

No LLM key needed — these run in CI.
"""

from __future__ import annotations

import uuid

import pytest

import app.services.extraction as extraction
from app.services.extraction import run_extraction
from evals.corpus import PLANTED_CORPUS, CONTROL_CORPUS, PLANTED_INDICES
from evals.harness import (
    seed_corpus,
    fetch_stored_patterns,
    score_planted,
    score_control,
)
from tests.conftest import create_test_user


HONEST_INSIGHT = (
    "We noticed a recurring spike of anticipatory anxiety before meetings "
    "with people above you — your boss, skip-levels, the director — followed "
    "by relief and self-criticism about over-preparing. Conversations with "
    "peers don't seem to trigger it."
)

UNRELATED_INSIGHT = (
    "We noticed you find disproportionate satisfaction in small household "
    "repairs and cooking rituals shared with people close to you."
)


def _pattern(insight: str, entry_ids: list[int], confidence: float = 0.5) -> dict:
    return {
        "insight": insight,
        "category": "emotional",
        "confidence": confidence,
        "evidence_entry_ids": entry_ids,
        "contradiction_entry_ids": [],
        "domains": ["emotional"],
        "specificity": "contextual",
    }


async def _run_pipeline_with_mock(conn, corpus, mock_fn, monkeypatch):
    """Seed corpus, run the REAL pipeline with a mocked LLM, read back DB."""
    user_id = await create_test_user(conn, email=f"eval-{uuid.uuid4()}@test.com")
    id_map = await seed_corpus(conn, user_id, corpus)

    async def fake_llm(prompt: str):
        return mock_fn(id_map)

    monkeypatch.setattr(extraction, "_call_llm", fake_llm)
    result = await run_extraction(conn, user_id)
    stored = await fetch_stored_patterns(conn, user_id)
    planted_db_ids = {id_map[i] for i in PLANTED_INDICES if i in id_map}
    return result, stored, planted_db_ids


# ── HONEST extractor ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_honest_extractor_is_detected_on_planted_corpus(conn, monkeypatch):
    def honest(id_map):
        planted_ids = [id_map[i] for i in PLANTED_INDICES]
        return [_pattern(HONEST_INSIGHT, planted_ids)]

    result, stored, planted_ids = await _run_pipeline_with_mock(
        conn, PLANTED_CORPUS, honest, monkeypatch
    )
    score = score_planted(stored, planted_ids)

    assert score.detected, score.explain()
    assert score.evidence_precision == 1.0
    # And it flowed through the REAL lifecycle: 5 supports >= floor → hypothesis
    assert score.best_pattern.status == "hypothesis"
    assert result.promoted_to_hypothesis == 1


@pytest.mark.asyncio
async def test_honest_extractor_is_clean_on_control_corpus(conn, monkeypatch):
    def honest_on_control(id_map):
        return []  # an honest extractor finds no pattern where none exists

    _, stored, _ = await _run_pipeline_with_mock(
        conn, CONTROL_CORPUS, honest_on_control, monkeypatch
    )
    score = score_control(stored)
    assert score.clean, score.explain()


# ── LYING extractor: the reason this eval exists ─────────────────────


@pytest.mark.asyncio
async def test_lying_extractor_passes_lifecycle_but_fails_eval(conn, monkeypatch):
    """
    A fabricating extractor: plausible authority-anxiety insight, but the
    citations point at noise entries (pasta, the heron run, car trouble).

    The lifecycle machinery happily accepts it — floor met, promoted to
    hypothesis. Every lifecycle test would stay green. ONLY the eval's
    evidence-precision check catches the lie. This is the demonstration
    that green lifecycle tests do not mean extraction tells the truth.
    """
    noise_indices = [i for i, e in enumerate(PLANTED_CORPUS) if not e.planted]

    def liar(id_map):
        fake_evidence = [id_map[i] for i in noise_indices[:4]]
        return [_pattern(HONEST_INSIGHT, fake_evidence, confidence=0.8)]

    result, stored, planted_ids = await _run_pipeline_with_mock(
        conn, PLANTED_CORPUS, liar, monkeypatch
    )

    # The lie sails through the lifecycle: floor met, hypothesis created.
    assert result.promoted_to_hypothesis == 1, (
        "Setup assumption broken: the lie should pass the lifecycle machinery"
    )

    # The eval catches it: zero citations into the planted set.
    score = score_planted(stored, planted_ids)
    assert not score.detected, score.explain()
    assert score.planted_hits == 0
    assert score.evidence_precision == 0.0


@pytest.mark.asyncio
async def test_lying_extractor_is_flagged_on_control_corpus(conn, monkeypatch):
    def liar_on_control(id_map):
        ids = list(id_map.values())[:3]
        return [
            _pattern(
                "We noticed a consistent pattern of dread before social "
                "obligations that fades once you arrive.",
                ids,
                confidence=0.7,
            )
        ]

    _, stored, _ = await _run_pipeline_with_mock(
        conn, CONTROL_CORPUS, liar_on_control, monkeypatch
    )
    score = score_control(stored)
    assert not score.clean, "Fabrication on the control corpus must be flagged"
    assert len(score.fabrications) == 1
    # The scorecard names the fabricated insight for human review
    assert "dread" in score.fabrications[0].insight


# ── STATE-GAMING extractor: right rows, wrong story ──────────────────


@pytest.mark.asyncio
async def test_state_gaming_extractor_fails_signal_check(conn, monkeypatch):
    """
    Cites exactly the planted entries (perfect evidence precision!) but
    the insight text is about something else entirely. Being clever about
    WHICH rows to cite is not enough — the claim itself must carry the
    planted signal.
    """
    def gamer(id_map):
        planted_ids = [id_map[i] for i in PLANTED_INDICES]
        return [_pattern(UNRELATED_INSIGHT, planted_ids)]

    _, stored, planted_ids = await _run_pipeline_with_mock(
        conn, PLANTED_CORPUS, gamer, monkeypatch
    )
    score = score_planted(stored, planted_ids)
    assert not score.detected, score.explain()
    assert score.evidence_precision == 1.0  # citations were perfect...
    assert not score.insight_matches_signal  # ...but the story was false


# ── LAZY extractor ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lazy_extractor_is_not_detected(conn, monkeypatch):
    def lazy(id_map):
        return []

    _, stored, planted_ids = await _run_pipeline_with_mock(
        conn, PLANTED_CORPUS, lazy, monkeypatch
    )
    score = score_planted(stored, planted_ids)
    assert not score.detected
    assert score.all_patterns == []
