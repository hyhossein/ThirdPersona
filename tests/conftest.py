"""
Test fixtures for ThirdPersona.

Creates a fresh schema per test session, provides connection helpers
that set RLS context, and cleans up after each test.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

# Test database URL — uses the same DB but different schema state per run
TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://thirdpersona:localdev@localhost:5432/thirdpersona_test",
)
MAIN_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://thirdpersona:localdev@localhost:5432/thirdpersona",
)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def _create_test_db():
    """Create the test database if it doesn't exist."""
    conn = await asyncpg.connect(MAIN_DB_URL)
    try:
        await conn.execute("DROP DATABASE IF EXISTS thirdpersona_test")
        await conn.execute("CREATE DATABASE thirdpersona_test")
    finally:
        await conn.close()


@pytest_asyncio.fixture(scope="session")
async def _apply_migration(_create_test_db):
    """Apply the migration and provision the app role for RLS testing.

    Uses the SAME provisioning code as production (scripts/setup_db.py),
    so tests exercise the real role, not a test-only lookalike.
    """
    from scripts.setup_db import provision_app_role

    conn = await asyncpg.connect(TEST_DB_URL)
    try:
        migrations_dir = Path(__file__).parent.parent / "migrations"
        for migration_path in sorted(migrations_dir.glob("*.sql")):
            sql = migration_path.read_text()
            await conn.execute(sql)
        await provision_app_role(conn)
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def conn(_apply_migration):
    """
    Provide a connection wrapped in a transaction that rolls back after the test.
    This gives each test a clean slate without re-creating the schema.
    """
    connection = await asyncpg.connect(TEST_DB_URL)
    tr = connection.transaction()
    await tr.start()
    try:
        yield connection
    finally:
        await tr.rollback()
        await connection.close()


async def create_test_user(
    conn: asyncpg.Connection,
    email: str = "test@example.com",
    display_name: str = "Test User",
) -> uuid.UUID:
    """Create a user and return their ID."""
    row = await conn.fetchrow(
        """
        INSERT INTO users (email, display_name)
        VALUES ($1, $2)
        RETURNING id
        """,
        email,
        display_name,
    )
    return row["id"]


async def create_test_entry(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    text: str,
) -> int:
    """Create a diary entry and return its ID."""
    row = await conn.fetchrow(
        """
        INSERT INTO entries (user_id, text_content)
        VALUES ($1, $2)
        RETURNING id
        """,
        user_id,
        text,
    )
    return row["id"]


async def create_test_pattern(
    conn: asyncpg.Connection,
    user_id: uuid.UUID,
    insight: str = "We noticed a test pattern",
    category: str = "emotional",
    confidence: float = 0.5,
    status: str = "candidate",
) -> uuid.UUID:
    """Create a pattern with the given status and return its ID."""
    row = await conn.fetchrow(
        """
        INSERT INTO patterns (user_id, insight, category, confidence, domains, status)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        user_id,
        insight,
        category,
        confidence,
        ["emotional"],
        status,
    )
    return row["id"]


async def add_evidence(
    conn: asyncpg.Connection,
    pattern_id: uuid.UUID,
    entry_id: int,
    user_id: uuid.UUID,
    relation: str = "supports",
) -> None:
    """Link an entry as evidence for a pattern."""
    await conn.execute(
        """
        INSERT INTO pattern_evidence (pattern_id, entry_id, user_id, relation, weight)
        VALUES ($1, $2, $3, $4, 1.0)
        """,
        pattern_id,
        entry_id,
        user_id,
        relation,
    )


async def set_rls_context(conn: asyncpg.Connection, user_id: uuid.UUID) -> None:
    """Set the RLS session variable and drop to a non-superuser role.

    Superusers bypass RLS even with FORCE ROW LEVEL SECURITY.
    The role switch is transaction-local (is_local=true), so the rollback
    in the conn fixture restores superuser.

    set_config() is used instead of SET LOCAL because it parameterizes —
    no string interpolation in anything that establishes identity.
    ('role' is a settable GUC, so the role switch parameterizes the same way.)
    """
    await conn.execute(
        "SELECT set_config('app.current_user_id', $1, true)", str(user_id)
    )
    await conn.execute("SELECT set_config('role', $1, true)", "thirdpersona_app")
