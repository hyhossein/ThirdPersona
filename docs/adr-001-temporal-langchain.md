# ADR-001: Temporal and LangChain — adopted, each at the moment its problem arrives

Date: 2026-07-16 · Status: accepted

## Decision

Both tools are adopted into the roadmap, neither into today's hot path:

1. **Temporal enters at the consent layer.** Invitations, mutual-consent
   reveals, revocation propagation, and the discovery-hold are long-lived,
   multi-day, multi-party state machines — genuinely Temporal-shaped work.
   Until then, background extraction runs on a Postgres-native job queue
   (`migrations/004_jobs.sql`, `app/services/jobs.py`) whose worker
   functions are deliberately shaped as Temporal activities: one jobs row
   ≈ one workflow execution; the `ACTIVITIES` registry ≈ registered
   activities; claim/execute/backoff ≈ an activity retry policy. The
   later adoption is a port, not a rewrite.

2. **LangGraph (not LangChain classic) enters at the Persona Dialogue
   layer**, where a stateful agent with consent checks and scope
   enforcement at every step is the real problem. The extraction pipeline
   stays on the direct Anthropic SDK: it is a single well-scoped call
   whose quality is certified by the ground-truth evals (5/5 planted
   recall, absence probe 3/3 clean). A framework wrapping that call can
   only match those numbers while hiding the prompt from the eval
   discipline.

## Standing rule (unchanged)

Any change to the extraction path — model, framework, prompt — must
re-pass the full ground-truth eval suite before it ships. The eval is
the hiring bar; no tool is exempt.

## Consequences

- Deploy stays two lightweight services (API + worker) plus Postgres —
  no cluster ops before the product has users.
- The jobs table holds metadata only, carries no RLS, and the worker
  executes every job inside the job-owner's RLS context via set_config.
  The worker never bypasses row-level security.
- When the consent layer is designed (product decisions currently
  parked), Temporal onboarding is: stand up server (Railway template or
  Temporal Cloud), port `ACTIVITIES` functions, express the consent flow
  as workflows, retire `jobs.py`.
