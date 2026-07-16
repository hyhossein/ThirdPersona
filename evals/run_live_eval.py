"""
Standalone live eval runner with repeat sampling.

A single LLM run is a sample, not a verdict. This runs the planted and
control evals N times and reports rates:

    ANTHROPIC_API_KEY=sk-... python evals/run_live_eval.py --runs 5

Uses the admin DSN (throwaway eval users are created and deleted).
Exit code 0 iff planted recall == 100% AND control fabrication == 0%
across all runs — deliberately strict; loosen consciously, not by drift.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

import asyncpg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.services.extraction import run_extraction  # noqa: E402
from evals.corpus import PLANTED_CORPUS, CONTROL_CORPUS, PLANTED_INDICES  # noqa: E402
from evals.harness import (  # noqa: E402
    seed_corpus,
    fetch_stored_patterns,
    score_planted,
    score_control,
)


async def _one_run(conn: asyncpg.Connection, run_idx: int) -> tuple[bool, bool]:
    """Returns (planted_detected, control_clean) for one sample."""
    results = []
    for corpus, label in ((PLANTED_CORPUS, "planted"), (CONTROL_CORPUS, "control")):
        user_id = uuid.uuid4()
        await conn.execute(
            "INSERT INTO users (id, email, display_name) VALUES ($1, $2, 'Eval')",
            user_id,
            f"eval-{label}-{run_idx}-{user_id}@eval.local",
        )
        try:
            id_map = await seed_corpus(conn, user_id, corpus)
            await run_extraction(conn, user_id)
            stored = await fetch_stored_patterns(conn, user_id)
            if label == "planted":
                score = score_planted(
                    stored, {id_map[i] for i in PLANTED_INDICES}
                )
                results.append(score.detected)
            else:
                score = score_control(stored)
                results.append(score.clean)
            print(f"--- run {run_idx} / {label} ---")
            print(score.explain())
        finally:
            # Throwaway eval data — clean up regardless of outcome.
            await conn.execute(
                "DELETE FROM pattern_rejections WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM pattern_visibility WHERE user_id = $1", user_id
            )
            await conn.execute(
                "DELETE FROM pattern_evidence WHERE user_id = $1", user_id
            )
            await conn.execute("DELETE FROM patterns WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM entries WHERE user_id = $1", user_id)
            await conn.execute("DELETE FROM users WHERE id = $1", user_id)
    return results[0], results[1]


async def main(runs: int) -> int:
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY not set — cannot run the live eval.")
        print("Extraction quality remains UNPROVEN until this runs.")
        return 2

    conn = await asyncpg.connect(settings.admin_database_url)
    try:
        planted_hits = 0
        control_clean = 0
        for i in range(runs):
            detected, clean = await _one_run(conn, i)
            planted_hits += detected
            control_clean += clean

        print("\n================ SCORECARD ================")
        print(f"Planted-pattern recall : {planted_hits}/{runs}")
        print(f"Control corpus clean   : {control_clean}/{runs}")
        print("===========================================")
        print(
            "Reminder: this measures extraction against ONE synthetic ground "
            "truth. It is evidence, not proof, that patterns are true for "
            "real people. User recognition remains the only ground truth."
        )
        return 0 if (planted_hits == runs and control_clean == runs) else 1
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.runs)))
