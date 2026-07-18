"""
Database connection pool and RLS-aware dependency injection.

Every API request runs inside a transaction with SET LOCAL app.current_user_id,
so RLS policies filter all queries to the authenticated user's data.
"""

from __future__ import annotations

import asyncpg
from fastapi import Depends, Header, HTTPException
from typing import AsyncGenerator
import uuid

_pool: asyncpg.Pool | None = None


class PrivilegedConnectionError(RuntimeError):
    """Raised when the app's runtime DB role could silently bypass RLS."""


async def assert_least_privilege(conn: asyncpg.Connection) -> None:
    """
    Refuse to run on a connection whose role bypasses RLS.

    Superusers and BYPASSRLS roles ignore row-level security even with
    FORCE ROW LEVEL SECURITY — every policy passes green while enforcing
    nothing. This guard makes that failure loud at boot instead of silent
    in production.
    """
    row = await conn.fetchrow(
        """
        SELECT rolname, rolsuper, rolbypassrls
        FROM pg_roles
        WHERE rolname = current_user
        """
    )
    if row is None:
        raise PrivilegedConnectionError(
            "Could not determine the runtime role's privileges."
        )
    if row["rolsuper"] or row["rolbypassrls"]:
        raise PrivilegedConnectionError(
            f"Runtime role '{row['rolname']}' has "
            f"{'SUPERUSER' if row['rolsuper'] else 'BYPASSRLS'} — "
            "RLS would be silently bypassed. The app must connect as a "
            "non-privileged role (thirdpersona_app). Migrations use the "
            "admin DSN separately (scripts/setup_db.py)."
        )


async def init_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    # Boot-time guard: verify the runtime role cannot bypass RLS.
    async with _pool.acquire() as conn:
        await assert_least_privilege(conn)
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


# Identity now lives in app.auth (JWT verification + JIT provisioning,
# with an explicit dev-only header mode). Re-exported here so routers'
# imports keep working.
from app.auth import get_current_user_id  # noqa: E402, F401


async def get_db(
    user_id: uuid.UUID = Depends(get_current_user_id),
) -> AsyncGenerator[asyncpg.Connection, None]:
    """
    Yield a database connection with RLS context set to the authenticated user.

    SET LOCAL scopes the setting to this transaction. When the transaction
    ends (commit or rollback), the setting disappears. If no X-User-ID is
    provided, the dependency raises before we reach the DB.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            # set_config(..., is_local=true) is exactly equivalent to SET LOCAL
            # but is a regular function call, so it parameterizes. No string
            # interpolation is permitted anywhere in the identity path —
            # "the input is a validated UUID" is a promise, not a mechanism.
            await conn.execute(
                "SELECT set_config('app.current_user_id', $1, true)", str(user_id)
            )
            yield conn
            await tr.commit()
        except Exception:
            await tr.rollback()
            raise


# NOTE: There is deliberately no get_db_no_rls() here.
# Extraction operates for exactly one known user, so it runs INSIDE that
# user's RLS context (get_db) — least privilege. If a true cross-user
# pipeline role ever becomes necessary, it gets its own connection pool,
# its own DSN, and its own explicit justification. Not a convenience helper.
