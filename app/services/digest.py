"""
Pattern digest builder (spec §3.2).

A compact, DETERMINISTIC rendering of the user's current pattern state,
built by SQL alone — no LLM call, no summarization drift. The digest
replaces the full corpus in the incremental extraction prompt.

Contents:
  - active + hypothesis patterns: id, insight, category, evidence_count,
    last_evidence date, specificity, status
  - candidates too — the weak-signal ledger (spec §3.4). A slow-burn
    pattern that never shows twice in any single window accumulates
    evidence across windows ONLY because its candidate row appears here
    and the model can reinforce it by id.
  - rejected patterns with reasons (hard negatives, as today)

Pattern UUIDs are included in each line so the model can emit
(pattern_id, entry_id, relation) reinforce triples that reference them.
"""

from __future__ import annotations

import uuid

import asyncpg

# Statuses rendered as live, reinforceable patterns.
_LIVE_STATUSES = ("active", "hypothesis", "candidate")


def _render_pattern_line(r: asyncpg.Record) -> str:
    last = r["last_evidence"].date().isoformat() if r["last_evidence"] else "never"
    return (
        f"- [{r['status']}] id={r['id']} ({r['category']}, "
        f"evidence={r['evidence_count']}, last_evidence={last}, "
        f"specificity={r['specificity']}) {r['insight']}"
    )


async def build_pattern_digest(
    conn: asyncpg.Connection, user_id: uuid.UUID
) -> str:
    """Render the user's pattern state as a compact, deterministic digest."""
    live_rows = await conn.fetch(
        """
        SELECT id, insight, category, evidence_count, last_evidence,
               specificity, status
        FROM patterns
        WHERE user_id = $1 AND status = ANY($2::text[])
        ORDER BY array_position($2::text[], status), created_at, id
        """,
        user_id,
        list(_LIVE_STATUSES),
    )

    rejected_rows = await conn.fetch(
        """
        SELECT p.insight, p.category, pr.reason
        FROM pattern_rejections pr
        JOIN patterns p ON p.id = pr.pattern_id
        WHERE pr.user_id = $1
        ORDER BY pr.rejected_at DESC, pr.id
        """,
        user_id,
    )

    sections: list[str] = []

    sections.append("### Known patterns (reinforce these by id when the window supports or contradicts them)")
    if live_rows:
        sections.extend(_render_pattern_line(r) for r in live_rows)
    else:
        sections.append("None yet.")

    sections.append("")
    sections.append("### Previously rejected patterns (hard negatives — do NOT rediscover)")
    if rejected_rows:
        sections.extend(
            f"- [{r['category']}] {r['insight']} (reason: {r['reason'] or 'none given'})"
            for r in rejected_rows
        )
    else:
        sections.append("None yet.")

    return "\n".join(sections)
