-- ================================================================
-- 004: Background jobs (the 11pm loop)
-- ================================================================
-- Metadata-only queue: kind + user_id + scheduling state. NO diary
-- content ever enters this table (payload is deliberately absent) —
-- which is why it carries no RLS: the worker must see jobs across
-- users to claim them, and there is nothing sensitive to isolate.
-- The worker then EXECUTES each job inside that user's RLS context
-- (set_config per job); it never bypasses row-level security.
--
-- Shaped for a later Temporal port: one row ~= one workflow execution;
-- claim/execute/retry-with-backoff ~= activity semantics. See
-- docs/adr-001-temporal-langchain.md.

CREATE TABLE IF NOT EXISTS jobs (
    id            bigint      PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id       uuid        NOT NULL REFERENCES users(id),
    kind          text        NOT NULL CHECK (kind IN ('extract')),
    status        text        NOT NULL DEFAULT 'queued'
                              CHECK (status IN ('queued', 'running', 'done', 'failed')),
    run_at        timestamptz NOT NULL DEFAULT now(),
    attempts      int         NOT NULL DEFAULT 0,
    max_attempts  int         NOT NULL DEFAULT 3,
    last_error    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_claimable ON jobs (run_at) WHERE status = 'queued';
-- Debounce: at most one queued extraction per user at a time.
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_queued_per_user
    ON jobs (user_id, kind) WHERE status = 'queued';
