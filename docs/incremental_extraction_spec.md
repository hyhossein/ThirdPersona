# Incremental Extraction — Specification

**Status: SPECIFIED, NOT APPROVED FOR BUILD.**

> ## ⛔ Precondition — read before writing any code
>
> Do **not** build this until the live ground-truth eval has run and passed:
>
> - `python evals/run_live_eval.py --runs 5`
> - **Planted-pattern recall ≥ 4/5**
> - **Control corpus clean 5/5** (zero fabrications — this bar is absolute)
>
> If the eval fails, extraction itself is the problem and this spec is
> premature optimization of a broken engine. Fix extraction, re-run,
> then return here. This banner is the gate; deleting it is not passing it.

---

## 1. The problem

Extraction today is O(corpus): every run stuffs the user's entire entry
history into one prompt. At 50 entries that's one cheap call. At 5,000
entries (~2 years of daily use, ~200 tokens/entry) it's ~1M tokens per
run — over context limits, slow, and expensive enough to be the product's
cost floor. Re-reading everything to notice one new thing is the single
real scaling constraint in the backend. Agents and extra models solve
nothing here; a bounded context does.

**Target invariant:** per-run cost is O(new entries + pattern digest),
bounded by a constant regardless of corpus size.

## 2. What must NOT change

The trust architecture is untouched. This spec adds no new authority:

- The lifecycle (candidate → hypothesis → active) and its DB triggers.
- The evidence floor (creation gate) and the confirmation gate.
- RLS, the non-superuser runtime role, the boot guard.
- The rejection feedback loop and circuit breaker.
- The rule that confidence reflects evidence volume, not model certainty.

Incremental extraction changes *what the model reads*, never *what the
database enforces*. Agents propose; the database disposes.

## 3. Design

### 3.1 Extraction watermark

New table (no trust-bearing tables are modified):

```sql
CREATE TABLE extraction_runs (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid        NOT NULL REFERENCES users(id),
    kind            text        NOT NULL CHECK (kind IN ('discover', 'consolidate')),
    entries_through bigint      NOT NULL,   -- highest entry id covered by this run
    window_size     int         NOT NULL,
    prompt_version  text        NOT NULL,
    model           text        NOT NULL,
    stats           jsonb,
    ran_at          timestamptz NOT NULL DEFAULT now()
);
-- RLS: user-isolated like every other per-user table.
```

The watermark (`MAX(entries_through)` per user) defines "new entries."
It is updated in the same transaction that stores the run's candidates,
so a crashed run repeats safely (evidence inserts are `ON CONFLICT DO
NOTHING`; duplicate-insight candidates are skipped as today).

### 3.2 Pattern digest (replaces the full corpus in the prompt)

A compact, **deterministic** rendering of the user's current pattern
state, built by SQL, not by an LLM (no summarization drift, no extra
call):

- Active + hypothesis patterns: insight, category, evidence_count,
  last_evidence, specificity.
- **Candidates too** — see §3.4; this is the load-bearing decision.
- Rejected patterns with reasons (hard negatives — as today).

Size: ~30–60 tokens per pattern. A power user with 100 live patterns
costs ~5k tokens of digest — bounded, and prunable by recency if ever
needed.

### 3.3 The extraction window

New entries since the watermark, **plus an overlap tail**: the previous
`min(10 entries, 14 days)`, whichever is larger. The overlap gives local
continuity ("this connects to what you wrote last week") without
unbounded context.

### 3.4 Three operations

**Discover** (every run). Find *new* candidate patterns in the window,
given the digest as context. Instruction change from today: the model
may propose a candidate on as little as **1–2 supporting entries**.
This sounds like loosening; it is not — candidates are invisible to the
user and the evidence floor still blocks promotion. Candidates become
the **weak-signal ledger**: the mechanism by which a slow-burn pattern
(one instance per month, never 2 in any window) accumulates evidence
across windows until the floor promotes it. The lifecycle we already
built is the cross-window memory. No new machinery.

**Reinforce** (same call, second output section). For each digest
pattern — *including candidates* — which window entries support or
contradict it? Output: (pattern_id, entry_id, relation) triples. Stored
as `pattern_evidence` rows; the existing promotion trigger does the
rest. This is how long-range patterns grow without full-corpus reads.

**Consolidate** (periodic: every ~10 discover runs, or monthly, or when
a user's contradiction ratio spikes). Operates on the *pattern set*, not
the raw corpus: merge near-duplicate patterns (supersession, already in
the lifecycle), surface tension pairs, propose archiving stale
candidates (no new evidence in 90 days). Optionally retrieval-assisted:
use `entry_embeddings` to fetch the handful of entries most similar to a
starving candidate and check them explicitly — a targeted read, never a
full scan.

### 3.5 Scheduling

Extraction becomes a background job (Taskiq or arq — pick one, both fit;
arq is lighter for a single-queue system). Trigger: N≥5 new entries
since last run OR 72h elapsed with ≥1 new entry. **Never synchronous
with entry save.** The `POST /patterns/extract` endpoint stays as a
manual trigger that enqueues the same job. Per-user jobs are independent
— horizontal scaling is trivial and the LLM spend is the only floor.

### 3.6 Cost model (the reason this spec exists)

| | Full-corpus @ 5k entries | Incremental |
|---|---|---|
| Prompt tokens/run | ~1,000,000 (impossible) | ~8k (window ~4k + digest ~2.5k + instructions ~1.5k) |
| Growth | O(corpus) | O(1) bounded |
| Feasible cadence | never | every few days per user, cheaply |

Roughly two orders of magnitude cheaper per run at scale, and it's the
difference between "works in the demo" and "works in year two."

## 4. The characteristic failure mode — and the eval that catches it

Incremental extraction has one way of silently destroying the product:
**cross-window pattern loss.** A pattern whose evidence arrives thinly —
one entry a month — may never show two instances inside any single
window, so Discover never proposes it, so Reinforce never has anything
to reinforce. The user's deepest rhythms are exactly these slow-burn
patterns. Full-corpus extraction would have caught them; a naive
incremental pipeline never will, and *nothing in production tells you
it's happening* — extraction still returns results, tests stay green,
the product just quietly stops seeing what matters most.

Therefore the incremental-mode ground-truth eval is **part of this spec,
not a follow-up**:

1. **Straddle corpus**: extend `evals/` with a planted pattern spread so
   that no window contains more than 2 planted entries (below any
   plausible within-window threshold), across ≥4 chronological windows.
2. **Replay harness**: feed the corpus incrementally — run the real
   pipeline after each window, watermark and all.
3. **Bars**:
   - The straddled pattern reaches **hypothesis by the final window**
     with ≥3 planted citations (proves the candidate ledger + reinforce
     loop carries weak signals across windows).
   - Control corpus replayed incrementally stays **clean** (fabrication
     pressure is higher with less context — measure it, don't assume).
   - **Parity bar**: incremental recall ≥ full-corpus recall on the same
     corpora. If incremental is worse, it does not ship.
4. **Instrument check first**, as before: a mock that only ever reports
   within-window patterns (a "goldfish extractor") must FAIL the
   straddle eval. If the harness can't catch the goldfish, the harness
   is broken. Build the mock test before the live one.

## 5. Build order (after the precondition passes)

1. Straddle-eval harness + goldfish-mock test (the instrument, ~1 day).
2. `extraction_runs` migration + digest builder (pure SQL, ~1 day).
3. Prompt v2: digest section + discover/reinforce dual output (~1 day).
4. Replay the mock evals; then live straddle eval, 5 runs.
5. Job queue wiring (arq/Taskiq) — mechanical, last, because it changes
   *when* extraction runs, not *whether it's right*.

## 6. Explicitly out of scope

- Anything agentic in the extraction path. One model call per discover
  run, one per consolidate run. If a future adversarial-skeptic pass is
  proposed, it must beat the *same eval* by a measured margin to earn
  its cost — the eval is the hiring bar for pipeline changes, not just
  models.
- New model integrations. The tiered Haiku/Sonnet/Opus split in the
  briefing stands; incremental extraction makes the *existing* tier
  affordable.
- All parked product decisions (sharing friction, discovery holds,
  third-party consent). This spec grants no new surface to any of them.
