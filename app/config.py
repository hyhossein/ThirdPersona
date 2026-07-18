from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Runtime DSN — MUST be a non-superuser role without BYPASSRLS.
    # RLS is the load-bearing access control layer; a superuser connection
    # bypasses it silently and turns every policy into decoration.
    # The app refuses to boot on a privileged connection (see database.assert_least_privilege).
    database_url: str = (
        "postgresql://thirdpersona_app:localdev_app@localhost:5432/thirdpersona"
    )

    # Admin DSN — used ONLY by migrations/setup (scripts/setup_db.py).
    # Never handed to the application runtime.
    admin_database_url: str = (
        "postgresql://thirdpersona:localdev@localhost:5432/thirdpersona"
    )

    # Auth. "dev" = X-User-ID header (local only; refuses to boot in
    # production). "jwt" = Bearer JWT verified against JWT_JWKS_URL
    # (Clerk or any OIDC provider), users JIT-provisioned from `sub`.
    auth_mode: str = "dev"
    jwt_jwks_url: str = ""
    jwt_issuer: str = ""
    thirdpersona_env: str = "development"

    anthropic_api_key: str = ""
    # Extraction model — mid-tier per the briefing's cost/depth split.
    # Any model change must re-pass the ground-truth eval before shipping.
    extraction_model: str = "claude-sonnet-4-6"
    min_evidence_floor: int = 3
    rejection_rate_threshold: float = 0.4  # 40% rejection rate = circuit breaker trips

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
