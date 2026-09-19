"""Schema verification tests for API Key models and migrations.

Validates model definitions and constraints without requiring a database
connection. Uses SQLAlchemy ORM __table__ metadata for column, index, and
constraint inspection.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")


class TestApiKeySchemaColumns:
    """Verify agent_api_keys model columns."""

    def test_api_keys_table_name(self):
        from app.db.models.agent_api_key import AgentApiKey
        assert AgentApiKey.__tablename__ == "agent_api_keys"

    def test_api_keys_has_required_columns(self):
        from app.db.models.agent_api_key import AgentApiKey
        col_names = {c.name for c in AgentApiKey.__table__.columns}
        required = {
            "id", "name", "key_hash", "key_prefix",
            "agent_identity_id", "agent_role_id", "status",
            "created_at", "last_used_at", "created_by", "expires_at",
        }
        assert required.issubset(col_names), f"Missing columns: {required - col_names}"

    def test_expires_at_column_is_nullable(self):
        from app.db.models.agent_api_key import AgentApiKey
        col = AgentApiKey.__table__.columns["expires_at"]
        assert col.nullable is True

    def test_key_hash_column_length(self):
        from app.db.models.agent_api_key import AgentApiKey
        col = AgentApiKey.__table__.columns["key_hash"]
        assert col.type.length == 64

    def test_key_prefix_column_length(self):
        from app.db.models.agent_api_key import AgentApiKey
        col = AgentApiKey.__table__.columns["key_prefix"]
        assert col.type.length == 16

    def test_name_column_length(self):
        from app.db.models.agent_api_key import AgentApiKey
        col = AgentApiKey.__table__.columns["name"]
        assert col.type.length == 128


class TestApiKeyUsageLogSchemaColumns:
    """Verify api_key_usage_logs model columns."""

    def test_usage_logs_table_name(self):
        from app.db.models.agent_api_key import ApiKeyUsageLog
        assert ApiKeyUsageLog.__tablename__ == "api_key_usage_logs"

    def test_usage_logs_has_required_columns(self):
        from app.db.models.agent_api_key import ApiKeyUsageLog
        col_names = {c.name for c in ApiKeyUsageLog.__table__.columns}
        required = {
            "id", "api_key_id", "action", "tool_name",
            "ip_address", "timestamp", "success",
        }
        assert required.issubset(col_names), f"Missing columns: {required - col_names}"


class TestApiKeyStatusEnum:
    """Verify ApiKeyStatus enum values."""

    def test_enum_has_active_and_revoked(self):
        from app.db.models.agent_api_key import ApiKeyStatus
        assert ApiKeyStatus.active.value == "active"
        assert ApiKeyStatus.revoked.value == "revoked"

    def test_enum_members(self):
        from app.db.models.agent_api_key import ApiKeyStatus
        values = {e.value for e in ApiKeyStatus}
        assert "active" in values
        assert "revoked" in values
        assert len(values) == 2


class TestApiKeyUsageActionEnum:
    """Verify ApiKeyUsageAction enum values."""

    def test_enum_has_required_actions(self):
        from app.db.models.agent_api_key import ApiKeyUsageAction
        values = {e.value for e in ApiKeyUsageAction}
        assert "validate" in values
        assert "load_skills" in values
        assert "tool_call" in values
        assert len(values) == 3


class TestApiKeyForeignKeyConstraints:
    """Verify foreign key constraints on agent_api_keys model."""

    def test_agent_identity_fk(self):
        from app.db.models.agent_api_key import AgentApiKey
        col = AgentApiKey.__table__.columns["agent_identity_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.column.table.name == "agent_identities"
        assert fk.column.name == "id"
        assert fk.ondelete == "CASCADE"

    def test_agent_role_fk(self):
        from app.db.models.agent_api_key import AgentApiKey
        col = AgentApiKey.__table__.columns["agent_role_id"]
        fks = list(col.foreign_keys)
        assert len(fks) == 1
        fk = fks[0]
        assert fk.column.table.name == "agent_roles"
        assert fk.column.name == "id"
        assert fk.ondelete == "CASCADE"


class TestApiKeyUniqueConstraints:
    """Verify unique constraints on the agent_api_keys model."""

    def test_unique_constraint_name(self):
        from app.db.models.agent_api_key import AgentApiKey
        uc_names = set()
        for constraint in AgentApiKey.__table__.constraints:
            if hasattr(constraint, 'name') and constraint.name:
                uc_names.add(constraint.name)
        assert "uq_agent_api_keys_name" in uc_names
        assert "uq_agent_api_keys_identity_role" not in uc_names


class TestApiKeyIndexes:
    """Verify indexes on api_keys models via __table_args__."""

    def test_key_hash_index(self):
        from app.db.models.agent_api_key import AgentApiKey
        index_names = {idx.name for idx in AgentApiKey.__table__.indexes}
        assert "ix_agent_api_keys_key_hash" in index_names

    def test_status_index(self):
        from app.db.models.agent_api_key import AgentApiKey
        index_names = {idx.name for idx in AgentApiKey.__table__.indexes}
        assert "ix_agent_api_keys_status" in index_names

    def test_usage_log_indexes(self):
        from app.db.models.agent_api_key import ApiKeyUsageLog
        index_names = {idx.name for idx in ApiKeyUsageLog.__table__.indexes}
        assert "ix_api_key_usage_logs_api_key_id" in index_names
        assert "ix_api_key_usage_logs_timestamp" in index_names
        assert "ix_api_key_usage_logs_action" in index_names


class TestKeyHashNeverPlaintext:
    """Negative test verifying key_hash column is not named in a way
    that suggests plaintext storage."""

    def test_model_no_plaintext_field(self):
        from app.db.models.agent_api_key import AgentApiKey
        col_names = {c.name for c in AgentApiKey.__table__.columns}
        assert "key_value" not in col_names
        assert "plaintext_key" not in col_names
        assert "secret" not in col_names
        assert "key_hash" in col_names  # hash-only storage
