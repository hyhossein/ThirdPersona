"""
Database setup: migration + runtime role provisioning.

Runs with the ADMIN DSN (owner privileges). The application runtime never
uses this DSN — it connects as thirdpersona_app, a non-superuser role
without BYPASSRLS, so row-level security actually applies.

Usage: python scripts/setup_db.py
"""

import asyncio
import asyncpg
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings

APP_ROLE = "thirdpersona_app"
# Local-dev password only. In production, provision credentials via the
# secret manager and rotate them — never commit real credentials.
APP_ROLE_PASSWORD = os.environ.get("APP_ROLE_PASSWORD", "localdev_app")


async def provision_app_role(conn: asyncpg.Connection) -> None:
    """Create the non-privileged runtime role and grant table access."""
    await conn.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN;
            END IF;
        END $$;
    """)
    # Ensure LOGIN + password even if the role pre-existed (e.g. created
    # NOLOGIN by an earlier test run). Explicitly strip privileges that
    # would bypass RLS, so a manually-privileged role gets demoted.
    await conn.execute(
        f"ALTER ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB "
        f"NOCREATEROLE PASSWORD '{APP_ROLE_PASSWORD}'"
    )
    await conn.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    await conn.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}"
    )
    await conn.execute(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}"
    )
    # Future tables created by this admin role inherit the grants.
    await conn.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE}"
    )
    await conn.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE}"
    )


async def main():
    conn = await asyncpg.connect(settings.admin_database_url)
    try:
        migrations_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "migrations",
        )
        for filename in sorted(os.listdir(migrations_dir)):
            if not filename.endswith(".sql"):
                continue
            with open(os.path.join(migrations_dir, filename)) as f:
                sql = f.read()
            try:
                await conn.execute(sql)
                print(f"Migration {filename} applied successfully.")
            except asyncpg.DuplicateTableError:
                print(f"Migration {filename}: tables already exist — skipped.")

        await provision_app_role(conn)
        print(f"Runtime role '{APP_ROLE}' provisioned (non-superuser, no BYPASSRLS).")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
