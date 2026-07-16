"""
Runtime connection privilege tests.

Background: RLS tests originally ran on a superuser connection, and
superusers bypass RLS even with FORCE ROW LEVEL SECURITY. Every RLS test
could have passed green while enforcing nothing. These tests make that
class of regression impossible to reintroduce silently:

1. The app's configured runtime DSN must resolve to a role that is
   neither SUPERUSER nor BYPASSRLS.
2. The boot guard (assert_least_privilege) must reject a privileged
   connection — so even a misconfigured deployment fails loudly at
   startup instead of running with decorative RLS.
3. RLS must actually filter rows on a real app-role connection —
   not on a superuser simulating one.
"""

from __future__ import annotations

import re
import uuid

import asyncpg
import pytest
import pytest_asyncio

from app.config import settings
from app.database import assert_least_privilege, PrivilegedConnectionError
from tests.conftest import (
    TEST_DB_URL,
    create_test_user,
    create_test_entry,
)

# The app role's DSN, pointed at the TEST database.
# Role attributes (SUPERUSER, BYPASSRLS) are cluster-wide, so asserting
# them here asserts them for every database in the cluster.
APP_TEST_DSN = re.sub(
    r"//[^@]+@", "//thirdpersona_app:localdev_app@", TEST_DB_URL
)


@pytest_asyncio.fixture
async def app_conn(_apply_migration):
    """A connection as the REAL runtime role — not a superuser in disguise."""
    conn = await asyncpg.connect(APP_TEST_DSN)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_runtime_dsn_role_is_not_privileged(app_conn):
    """
    The configured runtime role must not be SUPERUSER or BYPASSRLS.
    If this fails, RLS is decorative in production regardless of what
    every other RLS test says.
    """
    row = await app_conn.fetchrow(
        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )
    assert row["rolsuper"] is False, (
        f"Runtime role '{row['rolname']}' is SUPERUSER — RLS is silently bypassed"
    )
    assert row["rolbypassrls"] is False, (
        f"Runtime role '{row['rolname']}' has BYPASSRLS — RLS is silently bypassed"
    )


@pytest.mark.asyncio
async def test_configured_database_url_uses_app_role():
    """
    settings.database_url (what the app actually boots with) must name
    the app role, not the admin/superuser role. Guards against the DSN
    being 'temporarily' flipped back to the admin credentials.
    """
    assert "thirdpersona_app" in settings.database_url.split("@")[0], (
        "settings.database_url does not use the non-privileged app role"
    )
    assert settings.database_url != settings.admin_database_url, (
        "Runtime DSN and admin DSN are identical — migrations privileges "
        "leaked into the application runtime"
    )


@pytest.mark.asyncio
async def test_boot_guard_rejects_privileged_connection(conn):
    """
    assert_least_privilege must raise on a superuser connection.
    This is the guard that turns a misconfigured deployment into a
    loud boot failure instead of silent RLS bypass.
    (The `conn` fixture connects as the superuser.)
    """
    with pytest.raises(PrivilegedConnectionError):
        await assert_least_privilege(conn)


@pytest.mark.asyncio
async def test_boot_guard_accepts_app_role(app_conn):
    """assert_least_privilege passes for the real runtime role."""
    await assert_least_privilege(app_conn)  # must not raise


@pytest.mark.asyncio
async def test_rls_filters_on_real_app_connection(app_conn, _apply_migration):
    """
    End-to-end RLS check on the actual runtime role:
    data created (and committed) by an admin connection for two users;
    the app connection with user A's context sees only A's rows;
    with no context, nothing.

    Uses its own committing admin connection — the rollback-wrapped `conn`
    fixture would keep the seed data invisible to the app connection.
    """
    admin = await asyncpg.connect(TEST_DB_URL)
    user_a = user_b = None
    try:
        user_a = await create_test_user(admin, email=f"rls-a-{uuid.uuid4()}@test.com")
        user_b = await create_test_user(admin, email=f"rls-b-{uuid.uuid4()}@test.com")
        entry_a = await create_test_entry(admin, user_a, "A's private entry")
        entry_b = await create_test_entry(admin, user_b, "B's private entry")

        async with app_conn.transaction():
            await app_conn.execute(
                "SELECT set_config('app.current_user_id', $1, true)", str(user_a)
            )
            visible = {r["id"] for r in await app_conn.fetch("SELECT id FROM entries")}
            assert entry_a in visible, "App role should see the context user's entry"
            assert entry_b not in visible, "App role must NOT see another user's entry"

        # Fresh transaction, no context set → safe default is zero rows.
        async with app_conn.transaction():
            none_visible = await app_conn.fetch("SELECT id FROM entries")
            assert none_visible == [], (
                "With no RLS context, the app connection must see nothing"
            )
    finally:
        for uid in (user_a, user_b):
            if uid is not None:
                await admin.execute("DELETE FROM entries WHERE user_id = $1", uid)
                await admin.execute("DELETE FROM users WHERE id = $1", uid)
        await admin.close()
