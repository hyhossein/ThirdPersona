-- ThirdPersona: Incremental extraction watermark (spec §3.1)
--
-- Additive only. No trust-bearing table is modified: no trigger, no
-- existing RLS policy, no lifecycle change. This table records which
-- entries each extraction run has covered, so incremental runs read
-- O(new entries) instead of O(corpus).

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

CREATE INDEX idx_extraction_runs_user ON extraction_runs (user_id, entries_through DESC);

-- RLS: user-isolated like every other per-user table.
ALTER TABLE extraction_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE extraction_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY extraction_runs_isolation ON extraction_runs
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);
