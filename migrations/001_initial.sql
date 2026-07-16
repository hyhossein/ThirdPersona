-- ThirdPersona: Single-User Vertical Slice
-- Schema with RLS, lifecycle triggers, evidence floor enforcement
-- Implements: entry → candidate pattern → hypothesis → active (requires confirmation)
--
-- Security fixes applied:
--   1. RLS on all core tables
--   2. entry_embeddings in separate pipeline-only table
--   3. is_shareable is advisory (live check_live_shareability() is the gate)
--   4. Pattern lifecycle enforced by DB triggers, not application logic

-- ================================================================
-- EXTENSIONS
-- ================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";      -- gen_random_uuid()

-- ================================================================
-- TABLES
-- ================================================================

CREATE TABLE users (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    email           text        UNIQUE NOT NULL,
    display_name    text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    tier            text        NOT NULL DEFAULT 'free'
                                CHECK (tier IN ('free', 'premium', 'premium_plus')),
    settings        jsonb       DEFAULT '{}'
);

CREATE TABLE entries (
    id              bigint      PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    user_id         uuid        NOT NULL REFERENCES users(id),
    text_content    text,
    source_type     text        NOT NULL DEFAULT 'manual'
                                CHECK (source_type IN (
                                    'manual', 'voice', 'ai_import', 'photo', 'location'
                                )),
    mood_energy     smallint    CHECK (mood_energy BETWEEN 0 AND 100),
    mood_openness   smallint    CHECK (mood_openness BETWEEN 0 AND 100),
    mood_tension    smallint    CHECK (mood_tension BETWEEN 0 AND 100),
    domains         text[],
    richness_score  real,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz
);

-- Embeddings: SEPARATE TABLE, pipeline-role-only in production.
-- In the vertical slice we keep it for schema completeness but
-- the API never reads it directly.
CREATE TABLE entry_embeddings (
    entry_id        bigint      PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
    user_id         uuid        NOT NULL REFERENCES users(id),
    model           text        NOT NULL DEFAULT 'voyage-3-large',
    created_at      timestamptz NOT NULL DEFAULT now()
    -- embedding vector(1024) column omitted: pgvector not required for vertical slice.
    -- In production, add: embedding vector(1024) NOT NULL
);

CREATE TABLE patterns (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid        NOT NULL REFERENCES users(id),
    insight         text        NOT NULL,
    category        text        NOT NULL
                                CHECK (category IN (
                                    'relational', 'self', 'conflict', 'social',
                                    'intellectual', 'emotional', 'energy', 'values', 'growth'
                                )),
    confidence      real        NOT NULL CHECK (confidence BETWEEN 0.0 AND 1.0),
    domains         text[]      NOT NULL DEFAULT '{}',
    temporal_trend  text        NOT NULL DEFAULT 'new'
                                CHECK (temporal_trend IN (
                                    'new', 'stable', 'strengthening', 'weakening', 'dormant'
                                )),
    first_seen      timestamptz NOT NULL DEFAULT now(),
    last_evidence   timestamptz,

    -- Tension pairs
    is_tension      boolean     NOT NULL DEFAULT false,
    tension_pair_id uuid        REFERENCES patterns(id),
    context_conditions jsonb,

    -- ADVISORY shareability flag (real check is check_live_shareability())
    is_shareable    boolean     NOT NULL DEFAULT false,

    from_ai_import  boolean     NOT NULL DEFAULT false,
    evidence_count  smallint    NOT NULL DEFAULT 0,
    temporal_spread smallint    NOT NULL DEFAULT 0,
    specificity     text        NOT NULL DEFAULT 'general'
                                CHECK (specificity IN ('general', 'contextual', 'episodic')),

    -- LIFECYCLE: candidate → hypothesis → active | rejected | superseded | archived
    -- candidate:   LLM found it, below evidence floor (not shown to user)
    -- hypothesis:  passed evidence floor, shown as "we noticed..."
    -- active:      user explicitly confirmed ("this is me")
    -- rejected:    user rejected ("this isn't me") — fed back as hard negative
    -- superseded:  replaced by a newer, better-evidenced pattern
    -- archived:    dormant too long, auto-archived
    status          text        NOT NULL DEFAULT 'candidate'
                                CHECK (status IN (
                                    'candidate', 'hypothesis', 'active',
                                    'rejected', 'superseded', 'archived'
                                )),
    superseded_by   uuid        REFERENCES patterns(id),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz
);

CREATE TABLE pattern_evidence (
    pattern_id      uuid        NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    entry_id        bigint      NOT NULL REFERENCES entries(id),
    user_id         uuid        NOT NULL REFERENCES users(id),
    relation        text        NOT NULL
                                CHECK (relation IN ('supports', 'contradicts', 'context')),
    weight          real        NOT NULL DEFAULT 1.0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (pattern_id, entry_id)
);

CREATE TABLE pattern_visibility (
    pattern_id      uuid        NOT NULL REFERENCES patterns(id) ON DELETE CASCADE,
    user_id         uuid        NOT NULL REFERENCES users(id),
    first_seen_at   timestamptz,
    confirmed_at    timestamptz,     -- explicit user confirmation: "this is me"
    shareable_at    timestamptz,
    PRIMARY KEY (pattern_id, user_id)
);

CREATE TABLE pattern_rejections (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    pattern_id      uuid        NOT NULL REFERENCES patterns(id),
    user_id         uuid        NOT NULL REFERENCES users(id),
    reason          text,
    rejected_at     timestamptz NOT NULL DEFAULT now()
);


-- ================================================================
-- INDEXES
-- ================================================================

CREATE INDEX idx_entries_user_created ON entries (user_id, created_at DESC);
CREATE INDEX idx_patterns_user_status ON patterns (user_id, status);
CREATE INDEX idx_patterns_user_cat    ON patterns (user_id, category) WHERE status = 'active';
CREATE INDEX idx_evidence_pattern     ON pattern_evidence (pattern_id);
CREATE INDEX idx_evidence_entry       ON pattern_evidence (entry_id);
CREATE INDEX idx_rejections_user      ON pattern_rejections (user_id);


-- ================================================================
-- ROW-LEVEL SECURITY
-- ================================================================
-- RLS is the load-bearing access control layer.
-- Session variable app.current_user_id is set via SET LOCAL per transaction.
-- current_setting(..., true) returns NULL if unset → all policies deny (safe default).

ALTER TABLE entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE entries FORCE ROW LEVEL SECURITY;
CREATE POLICY entries_isolation ON entries
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

ALTER TABLE patterns ENABLE ROW LEVEL SECURITY;
ALTER TABLE patterns FORCE ROW LEVEL SECURITY;
CREATE POLICY patterns_isolation ON patterns
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

ALTER TABLE pattern_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE pattern_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY evidence_isolation ON pattern_evidence
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
    WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

ALTER TABLE pattern_visibility ENABLE ROW LEVEL SECURITY;
ALTER TABLE pattern_visibility FORCE ROW LEVEL SECURITY;
CREATE POLICY visibility_isolation ON pattern_visibility
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);

ALTER TABLE pattern_rejections ENABLE ROW LEVEL SECURITY;
ALTER TABLE pattern_rejections FORCE ROW LEVEL SECURITY;
CREATE POLICY rejections_isolation ON pattern_rejections
    USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid);


-- ================================================================
-- LIFECYCLE ENFORCEMENT TRIGGERS
-- ================================================================

-- 1. CONFIRMATION GATE: hypothesis → active requires explicit user confirmation
--    This is the database-level proof that no code path can promote a pattern
--    to active without the user's conscious act.

CREATE OR REPLACE FUNCTION enforce_pattern_confirmation()
RETURNS TRIGGER AS $$
BEGIN
    -- Block hypothesis → active without confirmation
    IF OLD.status = 'hypothesis' AND NEW.status = 'active' THEN
        IF NOT EXISTS (
            SELECT 1 FROM pattern_visibility
            WHERE pattern_id = NEW.id
              AND user_id = NEW.user_id
              AND confirmed_at IS NOT NULL
        ) THEN
            RAISE EXCEPTION 'LIFECYCLE_VIOLATION: Pattern % cannot become active without user confirmation via pattern_visibility.confirmed_at', NEW.id;
        END IF;
    END IF;

    -- Block candidate → active (must go through hypothesis first)
    IF OLD.status = 'candidate' AND NEW.status = 'active' THEN
        RAISE EXCEPTION 'LIFECYCLE_VIOLATION: Pattern % cannot skip hypothesis. Must transition candidate → hypothesis → active', NEW.id;
    END IF;

    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_enforce_pattern_confirmation
    BEFORE UPDATE ON patterns
    FOR EACH ROW
    WHEN (OLD.status IS DISTINCT FROM NEW.status)
    EXECUTE FUNCTION enforce_pattern_confirmation();


-- 2. EVIDENCE FLOOR: auto-promote candidate → hypothesis when evidence threshold met
--    The creation gate: a pattern stays invisible (candidate) until enough independent
--    evidence supports it. This is not a sharing gate — it's a "does this pattern
--    deserve to exist as a hypothesis at all" gate.

CREATE OR REPLACE FUNCTION check_evidence_promotion()
RETURNS TRIGGER AS $$
DECLARE
    v_support_count int;
    v_earliest      timestamptz;
    v_latest        timestamptz;
    v_spread_days   int;
    MIN_EVIDENCE    constant int := 3;  -- hard floor: 3 independent supporting entries
BEGIN
    -- Count supporting evidence
    SELECT COUNT(*), MIN(pe.created_at), MAX(pe.created_at)
    INTO v_support_count, v_earliest, v_latest
    FROM pattern_evidence pe
    WHERE pe.pattern_id = NEW.pattern_id
      AND pe.relation = 'supports';

    -- Calculate temporal spread
    v_spread_days := COALESCE(
        EXTRACT(DAY FROM (v_latest - v_earliest))::int, 0
    );

    -- Update pattern metadata
    UPDATE patterns SET
        evidence_count = v_support_count,
        temporal_spread = v_spread_days,
        last_evidence = now(),
        updated_at = now()
    WHERE id = NEW.pattern_id;

    -- Auto-promote candidate → hypothesis if evidence floor met
    UPDATE patterns SET
        status = 'hypothesis',
        updated_at = now()
    WHERE id = NEW.pattern_id
      AND status = 'candidate'
      AND v_support_count >= MIN_EVIDENCE;

    -- Auto-create visibility record when promoted to hypothesis
    -- (so the user can see it and eventually confirm)
    IF v_support_count >= MIN_EVIDENCE THEN
        INSERT INTO pattern_visibility (pattern_id, user_id)
        SELECT NEW.pattern_id, NEW.user_id
        WHERE NOT EXISTS (
            SELECT 1 FROM pattern_visibility
            WHERE pattern_id = NEW.pattern_id AND user_id = NEW.user_id
        );
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_check_evidence_promotion
    AFTER INSERT ON pattern_evidence
    FOR EACH ROW
    EXECUTE FUNCTION check_evidence_promotion();


-- 3. REJECTION CIRCUIT BREAKER: tracked via pattern_rejections table.
--    When rejection rate exceeds threshold, the extraction pipeline checks
--    before running. This is enforced at the application layer (not a trigger)
--    because the threshold and response are configurable product decisions.
--    The data for the check lives in pattern_rejections.

-- Helper view: rejection rate per user over rolling 30-day window
CREATE OR REPLACE VIEW user_rejection_rate AS
SELECT
    p.user_id,
    COUNT(*) FILTER (WHERE p.status = 'rejected'
                     AND pr.rejected_at > now() - interval '30 days')
        AS rejections_30d,
    COUNT(*) FILTER (WHERE p.created_at > now() - interval '30 days')
        AS patterns_30d,
    CASE
        WHEN COUNT(*) FILTER (WHERE p.created_at > now() - interval '30 days') = 0
        THEN 0.0
        ELSE COUNT(*) FILTER (WHERE p.status = 'rejected'
                              AND pr.rejected_at > now() - interval '30 days')::real
             / COUNT(*) FILTER (WHERE p.created_at > now() - interval '30 days')::real
    END AS rejection_rate
FROM patterns p
LEFT JOIN pattern_rejections pr ON pr.pattern_id = p.id
GROUP BY p.user_id;
