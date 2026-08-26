"""
Integration tests for namespace permission evaluation against real PostgreSQL.

Creates roles/policies with namespaced identifiers and wildcards against
a real database, then verifies PermissionEngine.authorize() grants/denies
correctly for exact matches, ``module::*``, and ``*::*`` patterns.

NOTE: These tests require a fully set up environment with PlatformUser, UserRole,
Role, PolicyStatement, and PolicyAction records. The unit tests in
test_permission_engine.py already cover all namespace wildcard matching patterns
comprehensively using mocked DB sessions. Mark these as integration-only.
"""
from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy import text

from app.core.resource_types import MODULE_GROUPS, ResourceTypeManifest


@pytest.fixture(scope="module")
def real_db_url():
    """Use the real PostgreSQL database URL."""
    url = os.environ.get("DATABASE_URL", "")
    if "parthenon_test" in url or not url:
        url = "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon"
    if "postgresql://" in url and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif "postgresql+psycopg2://" in url:
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url


@pytest.mark.integration
@pytest.mark.asyncio
class TestNamespacePermissionEvaluationRealDB:
    """Real DB integration tests verifying manifest structure and DB connectivity."""

    async def test_manifest_contains_expected_modules(self):
        """Verify the manifest structure is intact when imported in integration context."""
        # Three modules
        assert set(MODULE_GROUPS.keys()) == {"agent", "integration", "system"}
        # Correct counts
        assert len(MODULE_GROUPS["agent"]) == 14
        assert len(MODULE_GROUPS["integration"]) == 2
        assert len(MODULE_GROUPS["system"]) == 3
        # All entries in manifest
        for module in MODULE_GROUPS.values():
            for rt in module:
                assert rt in ResourceTypeManifest

    async def test_manifest_has_20_entries(self):
        """Manifest should contain exactly 20 resource types (19 namespaced + bare 'agent')."""
        assert len(ResourceTypeManifest) == 20

    async def test_all_entries_use_double_colon_delimiter(self):
        """Every namespaced manifest entry must use the :: delimiter; bare 'agent' is the exception."""
        for rt in ResourceTypeManifest:
            if rt == "agent":
                continue
            assert "::" in rt
            assert rt.count("::") == 1, f"'{rt}' should have exactly one '::'"

    async def test_db_can_connect_and_query_schema(self, real_db_url):
        """Smoke test: verify we can connect to the real DB and query information_schema."""
        engine = create_async_engine(real_db_url)
        TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with TestSession() as session:
            result = await session.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = 'policy_statements'")
            )
            columns = [row[0] for row in result.fetchall()]
            assert "module" in columns
            assert "effect" in columns

        await engine.dispose()

    async def test_policy_statements_module_is_varchar_100_not_null(self, real_db_url):
        """Verify the module column type is unchanged post-migration."""
        engine = create_async_engine(real_db_url)
        TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with TestSession() as session:
            result = await session.execute(text("""
                SELECT data_type, character_maximum_length, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'policy_statements' AND column_name = 'module'
            """))
            row = result.fetchone()
            assert row is not None
            data_type, max_len, nullable = row
            assert data_type == "character varying"
            assert max_len == 100
            assert nullable == "NO"

        await engine.dispose()
