# ThirdPersona — Single-User Vertical Slice

Entry ingestion → pattern extraction → candidate → hypothesis → active lifecycle,
with database-enforced user confirmation and row-level security.

## Setup

```bash
docker compose up -d          # or a local Postgres 16
cp .env.example .env          # fill in ANTHROPIC_API_KEY for extraction
python scripts/setup_db.py    # migration + runtime role (admin DSN)
uvicorn app.main:app          # boots as thirdpersona_app (non-superuser)
python -m pytest tests/       # lifecycle + connection-privilege tests
```

The runtime connects as `thirdpersona_app` — a role with no SUPERUSER and no
BYPASSRLS. The app **refuses to boot** on a privileged connection, because a
privileged role bypasses row-level security silently. Migrations run separately
with the admin DSN. Never point `DATABASE_URL` at the admin role.

## The scoreboard, honestly

**What the passing tests prove:**

The pattern *lifecycle* is safe. A hypothesis cannot become active without the
user explicitly confirming it — enforced by a database trigger, not application
code. Candidates cannot skip stages. The evidence floor gates promotion.
Contradicting evidence doesn't count toward the floor. Rejections are recorded
and rate-limited by a circuit breaker. RLS isolates users on the real runtime
role, verified on a real non-superuser connection with a boot guard and
regression tests so the "superuser silently bypasses RLS" failure mode cannot
be reintroduced quietly.

**What the passing tests do NOT prove:**

Whether extraction produces patterns that are *true*. Every lifecycle test uses
fixture patterns injected by the test harness — they would pass identically if
the extraction engine produced complete garbage. The core product risk — does a
real person recognize themselves in what the system surfaces, or does it
confidently confabulate — is addressed by the ground-truth eval in `evals/`,
which is a *measurement*, not a guarantee. Until the live eval runs with real
model calls and hits its bars (planted-pattern recall with correct evidence
citations, no fabricated evidence on control corpora), extraction quality is
**unproven**. Green lifecycle tests are necessary, not sufficient.

## Layout

```
app/                    FastAPI app (RLS-scoped connections only)
migrations/001_initial.sql   Schema, RLS policies, lifecycle triggers
scripts/setup_db.py     Migration + app-role provisioning (admin DSN)
tests/                  Lifecycle + connection-privilege tests (no LLM needed)
evals/                  Extraction ground-truth eval (LLM required for live leg)
```
