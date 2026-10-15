"""Schema verification — decision_model_availability migration (8144e472dce9).

Runs DIRECTLY against the real PostgreSQL database (parthenon, where
alembic migrations are applied) via asyncpg — no ORM, no mocks:

- migration state: alembic_version at the change's revision
- table + columns exist (information_schema), incl. the nullable
  ``decision_tools.decision_model_availability_id`` FK column
- uniqueness constraint uq_decision_model_availability_provider_model on
  (decision_model_provider_id, model_name) present in the catalog
- negative constraint tests: duplicate (provider, model) rejected at the DB
  level; bogus provider id rejected by the FK (both inside a ROLLBACK —
  the live database is left untouched)
- disabled_reason defaults to 'manual'
- backward-compat invariant: legacy tools keep provider_model with a NULL
  availability reference
"""
from __future__ import annotations

import contextlib
import socket
import uuid

import pytest

DSN = "postgresql://parthenon:parthenon@localhost:5432/parthenon"
REVISION = "b7d2e9f4a1c8"


@contextlib.asynccontextmanager
async def _pg():
    """Real-DB connection; skips cleanly when Postgres is unreachable."""
    try:
        socket.create_connection(("localhost", 5432), timeout=1).close()
    except OSError:
        pytest.skip("PostgreSQL not reachable on localhost:5432")
    import asyncpg

    try:
        conn = await asyncpg.connect(DSN)
    except Exception:
        pytest.skip("parthenon Postgres database not reachable")
    try:
        yield conn
    finally:
        await conn.close()


class TestMigrationApplied:
    @pytest.mark.asyncio
    async def test_alembic_version_at_change_revision(self):
        async with _pg() as conn:
            head = await conn.fetchval("SELECT version_num FROM alembic_version")
        assert head == REVISION, (
            f"expected migration {REVISION} applied, DB is at {head}"
        )


class TestSchemaStructure:
    @pytest.mark.asyncio
    async def test_table_exists_with_expected_columns(self):
        async with _pg() as conn:
            cols = await conn.fetch(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'decision_model_availability'"
            )
        by_name = {r["column_name"]: r["is_nullable"] for r in cols}
        for required in (
            "id",
            "tenant_id",
            "model_name",
            "decision_model_provider_id",
            "is_disabled",
            "disabled_reason",
            "created_at",
            "updated_at",
        ):
            assert required in by_name, f"missing column {required}"
        assert by_name["model_name"] == "NO"
        assert by_name["decision_model_provider_id"] == "NO"
        assert by_name["tenant_id"] == "YES"

    @pytest.mark.asyncio
    async def test_unique_constraint_provider_model(self):
        async with _pg() as conn:
            rows = await conn.fetch(
                "SELECT tc.constraint_name, kcu.column_name "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name = kcu.constraint_name "
                "WHERE tc.table_name = 'decision_model_availability' "
                "AND tc.constraint_type = 'UNIQUE'"
            )
        by_constraint: dict[str, set[str]] = {}
        for r in rows:
            by_constraint.setdefault(r["constraint_name"], set()).add(r["column_name"])
        assert {"decision_model_provider_id", "model_name"} in [
            v for v in by_constraint.values()
        ], f"unique (provider, model) constraint missing: {by_constraint}"

    @pytest.mark.asyncio
    async def test_tool_model_reference_column_nullable(self):
        async with _pg() as conn:
            cols = await conn.fetch(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_name = 'decision_tools' AND column_name IN "
                "('decision_model_availability_id', 'provider_model')"
            )
        by_name = {r["column_name"]: r["is_nullable"] for r in cols}
        assert by_name.get("decision_model_availability_id") == "YES"
        assert "provider_model" in by_name

    @pytest.mark.asyncio
    async def test_fk_to_provider_with_cascade(self):
        async with _pg() as conn:
            rows = await conn.fetch(
                "SELECT ccu.table_name AS ref_table, rc.delete_rule "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name = kcu.constraint_name "
                "JOIN information_schema.constraint_column_usage ccu "
                "ON ccu.constraint_name = tc.constraint_name "
                "JOIN information_schema.referential_constraints rc "
                "ON rc.constraint_name = tc.constraint_name "
                "WHERE tc.table_name = 'decision_model_availability' "
                "AND tc.constraint_type = 'FOREIGN KEY' "
                "AND kcu.column_name = 'decision_model_provider_id'"
            )
        assert rows, "FK decision_model_availability → provider missing"
        assert rows[0]["ref_table"] == "system_one_provider_configs"
        assert rows[0]["delete_rule"] == "CASCADE"


class TestNegativeConstraints:
    """Constraint enforcement proven with real inserts inside a rolled-back
    transaction — the live database is left untouched."""

    @pytest.mark.asyncio
    async def test_duplicate_provider_model_rejected_at_db_level(self):
        async with _pg() as conn:
            provider_id = await conn.fetchval(
                "SELECT id FROM system_one_provider_configs LIMIT 1"
            )
            if provider_id is None:
                pytest.skip("no provider rows in the live database")
            model = f"schema-probe-{uuid.uuid4().hex[:8]}"
            tr = conn.transaction()
            await tr.start()
            try:
                await conn.execute(
                    "INSERT INTO decision_model_availability "
                    "(id, model_name, decision_model_provider_id, is_disabled) "
                    "VALUES ($1, $2, $3, false)",
                    uuid.uuid4(), model, provider_id,
                )
                with pytest.raises(Exception) as exc_info:
                    await conn.execute(
                        "INSERT INTO decision_model_availability "
                        "(id, model_name, decision_model_provider_id, is_disabled) "
                        "VALUES ($1, $2, $3, false)",
                        uuid.uuid4(), model, provider_id,
                    )
                assert "unique" in str(exc_info.value).lower()
            finally:
                await tr.rollback()

    @pytest.mark.asyncio
    async def test_bogus_provider_id_rejected_by_fk(self):
        async with _pg() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                with pytest.raises(Exception) as exc_info:
                    await conn.execute(
                        "INSERT INTO decision_model_availability "
                        "(id, model_name, decision_model_provider_id, is_disabled) "
                        "VALUES ($1, 'orphan-model', $2, false)",
                        uuid.uuid4(), uuid.uuid4(),
                    )
                assert "foreign key" in str(exc_info.value).lower()
            finally:
                await tr.rollback()

    @pytest.mark.asyncio
    async def test_disabled_reason_defaults_to_manual(self):
        async with _pg() as conn:
            cols = await conn.fetch(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'decision_model_availability' "
                "AND column_name = 'disabled_reason'"
            )
        assert cols, "disabled_reason column missing"
        assert "manual" in (cols[0]["column_default"] or "")


class TestLegacyBackwardCompat:
    @pytest.mark.asyncio
    async def test_existing_tool_rows_survive_with_null_reference(self):
        """Backward compat invariant: decision tools predating the change
        carry a NULL availability reference and keep their legacy
        provider_model — no data loss on upgrade."""
        async with _pg() as conn:
            rows = await conn.fetch(
                "SELECT provider_model, decision_model_availability_id "
                "FROM decision_tools LIMIT 50"
            )
        for r in rows:
            if r["decision_model_availability_id"] is None:
                assert r["provider_model"], (
                    "legacy tool lost its provider_model during migration"
                )
