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

    anthropic_api_key: str = ""
    min_evidence_floor: int = 3
    rejection_rate_threshold: float = 0.4  # 40% rejection rate = circuit breaker trips

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
