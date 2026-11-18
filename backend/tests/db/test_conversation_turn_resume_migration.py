"""Migration / schema verification against the REAL migrated PostgreSQL DB.

Task 7.1 — resumable-agent-turn-persistence (``has_db_changes: true``).

Verifies the applied ``992bbc77bf6a_add_conversation_turn_resume`` migration by
querying ``information_schema`` / ``pg_catalog`` (never ORM metadata alone):

- both new tables exist and reconcile exactly with the SQLAlchemy models
  (columns + nullability), so the migration and the models cannot drift;
- ``conversation_activities.active_resume_id`` exists, is nullable, and points
  at ``conversation_turn_resumes.id`` with ``ON DELETE SET NULL``;
- the three enum types carry exactly the documented value sets;
- the constraints behave at the DB level:
  * ``idempotency_key`` is unique (exactly one confirmed write per paused turn),
  * one checkpoint row per resume record (1:1),
  * at most one live (``is_terminal = false``) resume row per conversation
    session (partial unique index),
  * invalid ``state`` / ``resume_outcome`` / ``payload_kind`` values are
    rejected by the enum types,
  * deleting the conversation session cascades its resume + checkpoint rows;
- the indexes backing the claim/reaper sweep and the sessions-list projection
  exist;
- upgrade/downgrade integrity (gated: it mutates the shared dev schema).

Full downgrade/re-upgrade is gated behind ``PARTHENON_TEST_MIGRATION_CYCLE=1``.
"""
from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

RESUME_TABLE = "conversation_turn_resumes"
CHECKPOINT_TABLE = "conversation_turn_checkpoints"


@pytest.fixture(scope="module")
def real_db_url():
    """The migration-applied development database."""
    url = os.environ.get("DATABASE_URL", "")
    if "parthenon_test" in url or not url:
        url = "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon"
    if "postgresql://" in url and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif "postgresql+psycopg2://" in url:
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


@pytest_asyncio.fixture
async def db(real_db_url):
    """Per-test engine+session (asyncpg connections are loop-bound)."""
    engine = create_async_engine(real_db_url)
    SessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with SessionLocal() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def sessions(db):
    """Tracks conversation sessions created by a test and removes them (cascade)."""
    created: list[uuid.UUID] = []
    yield created
    if created:
        await db.rollback()
        await db.execute(
            text("DELETE FROM conversation_sessions WHERE id = ANY(:ids)"),
            {"ids": created},
        )
        await db.commit()


async def _scalar(db, query: str, params: dict | None = None):
    result = await db.execute(text(query), params or {})
    row = result.fetchone()
    return row[0] if row else None


async def _new_session(db, sessions: list[uuid.UUID]) -> uuid.UUID:
    """Insert a minimal conversation session and track it for cleanup."""
    session_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO conversation_sessions (id, channel, status, turn_count) "
            "VALUES (:id, 'web', 'active', 0)"
        ),
        {"id": session_id},
    )
    await db.flush()
    sessions.append(session_id)
    return session_id


def _resume_row(
    *,
    session_id: uuid.UUID,
    idempotency_key: str | None = None,
    state: str = "waiting_for_human",
    is_terminal: bool = False,
) -> dict:
    return {
        "id": uuid.uuid4(),
        "conversation_session_id": session_id,
        "state": state,
        "is_terminal": is_terminal,
        "resume_key": f"rk-{uuid.uuid4().hex}",
        "idempotency_key": idempotency_key or f"idem-{uuid.uuid4().hex}",
    }


_INSERT_RESUME = text(
    "INSERT INTO conversation_turn_resumes "
    "(id, conversation_session_id, state, is_terminal, resume_key, "
    " idempotency_key, write_applied, attempt_count) "
    "VALUES (:id, :conversation_session_id, :state, :is_terminal, :resume_key, "
    " :idempotency_key, false, 0)"
)


async def _insert_resume(db, row: dict) -> None:
    await db.execute(_INSERT_RESUME, row)


async def _insert_checkpoint(
    db,
    resume_id: uuid.UUID,
    *,
    payload_kind: str = "agent_turn_state",
    payload: str = '{"v": 1}',
) -> None:
    await db.execute(
        text(
            "INSERT INTO conversation_turn_checkpoints "
            "(id, resume_id, payload_kind, schema_version, payload, payload_bytes, "
            " is_consumed) VALUES "
            "(:id, :resume_id, :payload_kind, 1, CAST(:payload AS json), "
            " :payload_bytes, false)"
        ),
        {
            "id": uuid.uuid4(),
            "resume_id": resume_id,
            "payload_kind": payload_kind,
            "payload": payload,
            "payload_bytes": len(payload),
        },
    )


# ── A. Tables, columns, nullability ──────────────────────────────────────────


class TestTablesAndColumns:
    @pytest.mark.parametrize("table", [RESUME_TABLE, CHECKPOINT_TABLE])
    async def test_table_exists(self, db, table):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_name = :t AND table_schema = 'public'",
            {"t": table},
        )
        assert count == 1

    @pytest.mark.parametrize(
        "model",
        [
            pytest.param("ConversationTurnResume", id="resume-index"),
            pytest.param("ConversationTurnCheckpoint", id="checkpoint-payload"),
        ],
    )
    async def test_migration_matches_model_columns_and_nullability(self, db, model):
        """Every modelled column exists with the modelled nullability (no drift)."""
        import app.db.models.conversation_turn_resume as mod

        table = getattr(mod, model).__table__
        actual = {
            row[0]: row[1]
            for row in (
                await db.execute(
                    text(
                        "SELECT column_name, is_nullable FROM information_schema.columns "
                        "WHERE table_name = :t AND table_schema = 'public'"
                    ),
                    {"t": table.name},
                )
            )
        }
        expected = {col.name: ("YES" if col.nullable else "NO") for col in table.columns}
        assert actual, f"{table.name} has no columns in the migrated database"
        missing = set(expected) - set(actual)
        extra = set(actual) - set(expected)
        assert not missing, f"modelled columns missing from the DB: {sorted(missing)}"
        assert not extra, f"DB columns not modelled: {sorted(extra)}"
        mismatched = {
            name: (expected[name], actual[name])
            for name in expected
            if expected[name] != actual[name]
        }
        assert not mismatched, (
            f"{table.name} nullability drift (model, db): {mismatched}"
        )

    async def test_mandatory_index_columns_are_not_null(self, db):
        """Columns the resume lifecycle depends on can never be NULL."""
        checks = {
            RESUME_TABLE: [
                "conversation_session_id",
                "state",
                "is_terminal",
                "resume_key",
                "idempotency_key",
                "write_applied",
                "attempt_count",
                "created_at",
                "updated_at",
            ],
            CHECKPOINT_TABLE: [
                "resume_id",
                "payload_kind",
                "schema_version",
                "payload",
                "payload_bytes",
                "is_consumed",
            ],
        }
        for table, columns in checks.items():
            for column in columns:
                nullable = await _scalar(
                    db,
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c "
                    "AND table_schema = 'public'",
                    {"t": table, "c": column},
                )
                assert nullable == "NO", f"{table}.{column} must be NOT NULL"

    async def test_applied_marker_columns_are_nullable(self, db):
        """The applied marker is stamped in the write transaction, never required."""
        for column in (
            "applied_by_user_id",
            "applied_at",
            "applied_effect_summary",
            "resolved_at",
            "outcome_turn_id",
            "claimed_by_instance_id",
            "claim_expires_at",
            "terminal_reason_code",
            "terminal_message_key",
            "expires_at",
            "resume_outcome",
        ):
            nullable = await _scalar(
                db,
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c "
                "AND table_schema = 'public'",
                {"t": RESUME_TABLE, "c": column},
            )
            assert nullable == "YES", f"{RESUME_TABLE}.{column} must be nullable"

    async def test_activity_active_resume_id_is_nullable_fk(self, db):
        nullable = await _scalar(
            db,
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = 'conversation_activities' "
            "AND column_name = 'active_resume_id' AND table_schema = 'public'",
        )
        assert nullable == "YES"

        definition = await _scalar(
            db,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'conversation_activities'::regclass "
            "AND contype = 'f' "
            "AND pg_get_constraintdef(oid) LIKE '%active_resume_id%'",
        )
        assert definition is not None, "active_resume_id FK is missing"
        assert "conversation_turn_resumes(id)" in definition
        assert "ON DELETE SET NULL" in definition

    async def test_legacy_shaped_activity_row_stays_valid(self, db, sessions):
        """A pre-existing activity row (no resume link) still inserts as NULL."""
        session_id = await _new_session(db, sessions)
        await db.execute(
            text(
                "INSERT INTO conversation_activities "
                "(id, conversation_session_id, state, is_terminal) "
                "VALUES (:id, :s, 'thinking', false)"
            ),
            {"id": uuid.uuid4(), "s": session_id},
        )
        await db.flush()

        value = await _scalar(
            db,
            "SELECT active_resume_id FROM conversation_activities "
            "WHERE conversation_session_id = :s",
            {"s": session_id},
        )
        assert value is None


# ── Enum types ───────────────────────────────────────────────────────────────


class TestEnumTypes:
    @pytest.mark.parametrize(
        ("type_name", "expected"),
        [
            (
                "resume_state_enum",
                ["waiting_for_human", "resuming", "resolved", "unresumable"],
            ),
            (
                "resume_outcome_enum",
                [
                    "approved_applied",
                    "denied",
                    "cancelled",
                    "expired",
                    "superseded",
                    "resume_failed",
                ],
            ),
            (
                "checkpoint_payload_kind_enum",
                ["agent_turn_state", "conversation_state"],
            ),
        ],
    )
    async def test_enum_value_sets(self, db, type_name, expected):
        rows = await db.execute(
            text(
                "SELECT e.enumlabel FROM pg_type t "
                "JOIN pg_enum e ON e.enumtypid = t.oid "
                "WHERE t.typname = :n ORDER BY e.enumsortorder"
            ),
            {"n": type_name},
        )
        assert [row[0] for row in rows] == expected

    async def test_resume_columns_use_the_enum_types(self, db):
        for column, expected_type in (
            ("state", "resume_state_enum"),
            ("resume_outcome", "resume_outcome_enum"),
        ):
            udt = await _scalar(
                db,
                "SELECT udt_name FROM information_schema.columns "
                "WHERE table_name = :t AND column_name = :c "
                "AND table_schema = 'public'",
                {"t": RESUME_TABLE, "c": column},
            )
            assert udt == expected_type
        udt = await _scalar(
            db,
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = 'payload_kind' "
            "AND table_schema = 'public'",
            {"t": CHECKPOINT_TABLE},
        )
        assert udt == "checkpoint_payload_kind_enum"


# ── Constraints and indexes ──────────────────────────────────────────────────


class TestConstraintsAndIndexes:
    async def test_idempotency_key_is_unique(self, db):
        definition = await _scalar(
            db,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'conversation_turn_resumes'::regclass "
            "AND contype = 'u' "
            "AND pg_get_constraintdef(oid) LIKE '%idempotency_key%'",
        )
        assert definition is not None
        assert "UNIQUE" in definition

    async def test_checkpoint_is_one_to_one(self, db):
        definition = await _scalar(
            db,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'conversation_turn_checkpoints'::regclass "
            "AND contype = 'u'",
        )
        assert definition is not None
        assert "resume_id" in definition

    async def test_one_live_resume_per_session_partial_unique_index(self, db):
        definition = await _scalar(
            db,
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'conversation_turn_resumes' "
            "AND indexname = 'uq_conversation_turn_resumes_live_session'",
        )
        assert definition is not None, "partial unique live-resume index is missing"
        assert "UNIQUE" in definition
        assert "is_terminal = false" in definition.replace('"', "")

    @pytest.mark.parametrize(
        "index_name",
        [
            "ix_conversation_turn_resumes_conversation_session_id",
            "ix_conversation_turn_resumes_expires_at",
            "ix_conversation_turn_resumes_resume_key",
        ],
    )
    async def test_supporting_indexes_exist(self, db, index_name):
        count = await _scalar(
            db,
            "SELECT COUNT(*) FROM pg_indexes "
            "WHERE tablename = 'conversation_turn_resumes' AND indexname = :n",
            {"n": index_name},
        )
        assert count == 1

    @pytest.mark.parametrize(
        ("column", "expected_action"),
        [
            ("conversation_session_id", "CASCADE"),
            ("tenant_id", "SET NULL"),
            ("turn_id", "SET NULL"),
            ("intervene_request_id", "SET NULL"),
            ("applied_by_user_id", "SET NULL"),
            ("outcome_turn_id", "SET NULL"),
        ],
    )
    async def test_resume_foreign_key_actions(self, db, column, expected_action):
        definition = await _scalar(
            db,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'conversation_turn_resumes'::regclass "
            "AND contype = 'f' AND pg_get_constraintdef(oid) LIKE :c",
            {"c": f"%({column})%"},
        )
        assert definition is not None, f"{column} FK is missing"
        assert f"ON DELETE {expected_action}" in definition

    async def test_checkpoint_cascades_with_the_resume_record(self, db):
        definition = await _scalar(
            db,
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'conversation_turn_checkpoints'::regclass "
            "AND contype = 'f'",
        )
        assert definition is not None
        assert "conversation_turn_resumes(id)" in definition
        assert "ON DELETE CASCADE" in definition


# ── B. Negative constraint tests (must fail) ─────────────────────────────────


class TestNegativeConstraints:
    async def test_second_live_resume_for_one_session_is_rejected(
        self, db, sessions
    ):
        session_id = await _new_session(db, sessions)
        await _insert_resume(db, _resume_row(session_id=session_id))
        await db.flush()

        with pytest.raises(Exception):
            await _insert_resume(db, _resume_row(session_id=session_id))
            await db.flush()
        await db.rollback()

        live = await _scalar(
            db,
            "SELECT COUNT(*) FROM conversation_turn_resumes "
            "WHERE conversation_session_id = :s AND is_terminal = false",
            {"s": session_id},
        )
        assert live <= 1

    async def test_terminal_plus_live_resume_is_allowed(self, db, sessions):
        """A superseded/resolved row does not block the next pause."""
        session_id = await _new_session(db, sessions)
        await _insert_resume(
            db,
            _resume_row(
                session_id=session_id, state="unresumable", is_terminal=True
            ),
        )
        await _insert_resume(db, _resume_row(session_id=session_id))
        await db.flush()

        rows = await _scalar(
            db,
            "SELECT COUNT(*) FROM conversation_turn_resumes "
            "WHERE conversation_session_id = :s",
            {"s": session_id},
        )
        assert rows == 2

    async def test_duplicate_idempotency_key_is_rejected(self, db, sessions):
        first = await _new_session(db, sessions)
        second = await _new_session(db, sessions)
        key = f"idem-dup-{uuid.uuid4().hex}"
        await _insert_resume(
            db, _resume_row(session_id=first, idempotency_key=key)
        )
        await db.flush()

        with pytest.raises(Exception):
            await _insert_resume(
                db, _resume_row(session_id=second, idempotency_key=key)
            )
            await db.flush()
        await db.rollback()

    async def test_second_checkpoint_for_one_resume_is_rejected(self, db, sessions):
        session_id = await _new_session(db, sessions)
        row = _resume_row(session_id=session_id)
        await _insert_resume(db, row)
        await db.flush()
        await _insert_checkpoint(db, row["id"])
        await db.flush()

        with pytest.raises(Exception):
            await _insert_checkpoint(db, row["id"], payload='{"v": 2}')
            await db.flush()
        await db.rollback()

    async def test_invalid_resume_state_is_rejected_by_the_enum(self, db, sessions):
        session_id = await _new_session(db, sessions)
        with pytest.raises(Exception):
            await _insert_resume(
                db, _resume_row(session_id=session_id, state="not_a_state")
            )
            await db.flush()
        await db.rollback()

    async def test_invalid_resume_outcome_is_rejected_by_the_enum(
        self, db, sessions
    ):
        session_id = await _new_session(db, sessions)
        row = _resume_row(session_id=session_id)
        await _insert_resume(db, row)
        await db.flush()

        with pytest.raises(Exception):
            await db.execute(
                text(
                    "UPDATE conversation_turn_resumes SET resume_outcome = "
                    "'victorious' WHERE id = :id"
                ),
                {"id": row["id"]},
            )
            await db.flush()
        await db.rollback()

    async def test_invalid_payload_kind_is_rejected_by_the_enum(self, db, sessions):
        session_id = await _new_session(db, sessions)
        row = _resume_row(session_id=session_id)
        await _insert_resume(db, row)
        await db.flush()

        with pytest.raises(Exception):
            await _insert_checkpoint(db, row["id"], payload_kind="whole_world")
            await db.flush()
        await db.rollback()

    async def test_deleting_the_session_cascades_resume_and_checkpoint(
        self, db, sessions
    ):
        session_id = await _new_session(db, sessions)
        row = _resume_row(session_id=session_id)
        await _insert_resume(db, row)
        await db.flush()
        await _insert_checkpoint(db, row["id"])
        await db.commit()

        await db.execute(
            text("DELETE FROM conversation_sessions WHERE id = :s"),
            {"s": session_id},
        )
        await db.commit()

        assert (
            await _scalar(
                db,
                "SELECT COUNT(*) FROM conversation_turn_resumes "
                "WHERE conversation_session_id = :s",
                {"s": session_id},
            )
            == 0
        )
        assert (
            await _scalar(
                db,
                "SELECT COUNT(*) FROM conversation_turn_checkpoints "
                "WHERE resume_id = :r",
                {"r": row["id"]},
            )
            == 0
        )
        # Already deleted — keep cleanup from failing on a missing row.
        sessions.remove(session_id)


# ── C. Upgrade / downgrade integrity (gated) ─────────────────────────────────


@pytest.mark.skipif(
    os.environ.get("PARTHENON_TEST_MIGRATION_CYCLE") != "1",
    reason=(
        "Downgrade/re-upgrade mutates the SHARED development database schema; "
        "run explicitly with PARTHENON_TEST_MIGRATION_CYCLE=1 against a "
        "disposable database"
    ),
)
class TestMigrationReversibility:
    async def test_downgrade_upgrade_cycle(self, real_db_url):
        """``downgrade -1`` then ``upgrade head`` succeeds and restores the head."""
        import subprocess
        import sys

        backend_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        env = {**os.environ, "DATABASE_URL": real_db_url}

        def _alembic(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(
                [sys.executable, "-m", "alembic", *args],
                capture_output=True,
                text=True,
                cwd=backend_dir,
                env=env,
                check=False,
            )

        head_before = _alembic("current")
        assert head_before.returncode == 0, head_before.stderr
        assert "992bbc77bf6a" in head_before.stdout

        downgrade = _alembic("downgrade", "-1")
        assert downgrade.returncode == 0, downgrade.stderr

        engine = create_async_engine(real_db_url)
        try:
            async with engine.connect() as conn:
                gone = (
                    await conn.execute(
                        text(
                            "SELECT COUNT(*) FROM information_schema.columns "
                            "WHERE table_name = 'conversation_activities' "
                            "AND column_name = 'active_resume_id'"
                        )
                    )
                ).scalar_one()
                assert gone == 0
        finally:
            await engine.dispose()

        upgrade = _alembic("upgrade", "head")
        assert upgrade.returncode == 0, upgrade.stderr

        head_after = _alembic("current")
        assert head_after.returncode == 0, head_after.stderr
        assert "992bbc77bf6a" in head_after.stdout
