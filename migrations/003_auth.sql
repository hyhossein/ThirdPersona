-- ================================================================
-- 003: Real authentication
-- ================================================================
-- users.external_id links a user row to the identity provider's
-- subject claim (Clerk user id, or any OIDC 'sub'). Users are
-- JIT-provisioned on first authenticated request.

ALTER TABLE users ADD COLUMN IF NOT EXISTS external_id text;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_external_id
    ON users (external_id) WHERE external_id IS NOT NULL;
