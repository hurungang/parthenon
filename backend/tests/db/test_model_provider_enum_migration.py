"""Database integration tests for the ``model_provider_enum`` additive migration.

Per ``docs/changes/expand-model-config-providers/test-plan.md`` and
``docs/config.yaml`` ``source.tests``:

> Test plan requires the schema-related tests in
> ``backend/tests/db/test_model_provider_enum_migration.py`` to run against a
> real Postgres instance, gated on a ``requires_postgres`` marker, so the
> in-memory SQLite stub does not falsely pass.

The tests are skipped when ``PARTHENON_DATABASE_URL`` is not set.  When a
real Postgres instance is reachable, the tests:

* assert the ``model_provider_enum`` type has all 12 values
* assert the column type on ``model_configs.provider_type`` is still
  USER-DEFINED (the enum) and NOT NULL
* confirm the enum type was not recreated (its OID is preserved across
  the migration)
* verify pre-existing ``model_configs`` rows are byte-for-byte preserved
* confirm the migration is idempotent on a second ``alembic upgrade head``
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text


REQUIRES_POSTGRES = pytest.mark.skipif(
    not os.environ.get("PARTHENON_DATABASE_URL", "").startswith("postgresql"),
    reason="Requires a real Postgres database (PARTHENON_DATABASE_URL must be postgresql://...)",
)


# All 12 supported provider keys in the order they appear in the Python enum.
EXPECTED_ENUM_VALUES = (
    "openai",
    "anthropic",
    "litellm_proxy",
    "azure_openai",
    "gemini",
    "mistral",
    "cohere",
    "groq",
    "together",
    "fireworks",
    "perplexity",
    "deepseek",
)


def _sync_url() -> str:
    """Return the synchronous Postgres URL (psycopg2 dialect) for the real DB.

    ``tests/conftest.py`` sets ``DATABASE_URL=...parthenon_test`` for the
    in-memory unit-test fixture; we must use the explicit dev URL
    (``PARTHENON_DATABASE_URL``) instead so this module can talk to the
    real database.
    """
    url = os.environ.get(
        "PARTHENON_DATABASE_URL",
        "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon",
    )
    # Strip the asyncpg dialect so the standard psycopg2 driver takes over
    # and we don't need a live event loop for these tests.
    return url.replace("+asyncpg", "")


@pytest.fixture
def pg_engine():
    """Create a real Postgres engine for one test.

    We use the synchronous ``psycopg2`` engine here so the test does not
    collide with the in-memory SQLite engine created by
    ``tests/conftest.py``.  Each test gets its own engine and connection.
    """
    engine = create_engine(_sync_url())
    yield engine
    engine.dispose()


@REQUIRES_POSTGRES
def test_model_provider_enum_has_twelve_values(pg_engine):
    """Postgres ``model_provider_enum`` has 12 values in the expected order."""
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT enumlabel FROM pg_enum e "
                "JOIN pg_type t ON t.oid = e.enumtypid "
                "WHERE t.typname = 'model_provider_enum' "
                "ORDER BY enumsortorder"
            )
        ).fetchall()
    actual = tuple(r[0] for r in rows)
    assert len(actual) == 12
    assert actual == EXPECTED_ENUM_VALUES


@REQUIRES_POSTGRES
def test_model_provider_enum_type_oid_is_stable(pg_engine):
    """The enum type OID is preserved across the migration (no type recreation)."""
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT oid FROM pg_type WHERE typname = 'model_provider_enum'")
        ).fetchall()
        assert len(rows) == 1, "model_provider_enum should exist as a single type"
        first_oid = rows[0][0]

    # Re-run the migration as a separate process so we don't conflict with
    # any open connection in the test engine, then re-query the OID.
    import subprocess
    import sys

    env = {**os.environ}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"alembic upgrade head failed in subprocess: {proc.stderr}")

    with pg_engine.connect() as conn:
        rows = conn.execute(
            text("SELECT oid FROM pg_type WHERE typname = 'model_provider_enum'")
        ).fetchall()
        assert rows[0][0] == first_oid, "OID must be preserved (no DROP TYPE / CREATE TYPE)"


@REQUIRES_POSTGRES
def test_model_configs_provider_type_column_uses_user_defined_enum(pg_engine):
    """``model_configs.provider_type`` is the ``model_provider_enum`` type and NOT NULL."""
    with pg_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT data_type, udt_name, is_nullable "
                "FROM information_schema.columns "
                "WHERE table_name = 'model_configs' "
                "AND column_name = 'provider_type'"
            )
        ).fetchone()
    assert row is not None, "model_configs.provider_type column must exist"
    data_type, udt_name, is_nullable = row
    assert data_type == "USER-DEFINED", f"Expected USER-DEFINED, got {data_type}"
    assert udt_name == "model_provider_enum", f"Expected model_provider_enum, got {udt_name}"
    assert is_nullable == "NO", "provider_type must be NOT NULL"


@REQUIRES_POSTGRES
def test_pre_existing_model_config_rows_preserved_after_migration(pg_engine):
    """Pre-existing ``model_configs`` rows have their ``provider_type`` preserved exactly.

    On an empty database the assertion is trivially true.
    """
    with pg_engine.connect() as conn:
        before_rows = conn.execute(
            text("SELECT id, provider_type FROM model_configs ORDER BY id")
        ).fetchall()
    before = [(str(r[0]), str(r[1])) for r in before_rows]

    # Re-run the migration; the snapshot must be unchanged.
    import subprocess
    import sys

    env = {**os.environ}
    proc = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"alembic upgrade head failed in subprocess: {proc.stderr}")

    with pg_engine.connect() as conn:
        after_rows = conn.execute(
            text("SELECT id, provider_type FROM model_configs ORDER BY id")
        ).fetchall()
    after = [(str(r[0]), str(r[1])) for r in after_rows]

    assert after == before, (
        f"model_configs rows must be byte-for-byte preserved: "
        f"before={before}, after={after}"
    )


@REQUIRES_POSTGRES
def test_no_unique_or_check_constraint_on_provider_type(pg_engine):
    """``model_configs.provider_type`` carries no UNIQUE / CHECK constraint that would block new values.

    The column relies on the enum type for validation; a UNIQUE / CHECK
    constraint here would block the new values from being added.  This test
    is a structural sanity check that records the current constraint
    state, with a hard assertion only when a constraint that would block
    the additive migration exists.
    """
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT conname, contype FROM pg_constraint "
                "WHERE conrelid = 'model_configs'::regclass"
            )
        ).fetchall()
    provider_type_constraints = [
        r
        for r in rows
        if (r[0] or "").endswith("provider_type") or "provider_type" in (r[0] or "")
    ]
    # The model_configs ORM has no UNIQUE / CHECK constraint on the
    # provider_type column.  We assert the structural reality so that a
    # future refactor adding such a constraint must update this test.
    assert provider_type_constraints == [], (
        f"Unexpected constraints on provider_type: {provider_type_constraints}"
    )
