"""API tests for policy utility endpoints and role clone endpoint."""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.main import create_app
from app.db.session import get_db
from app.api.deps import require_permission
from app.middleware.auth import JWTAuthMiddleware
from app.core.resource_types import ResourceTypeManifest, RT_PERMISSIONS, RT_ROLE


def _bypass_auth():
    async def patched_dispatch(self, request, call_next):
        request.state.identity = {"sub": "user-sub", "roles": ["admin"]}
        request.state.platform_user_id = uuid.uuid4()
        return await call_next(request)

    return patch.object(JWTAuthMiddleware, "dispatch", patched_dispatch)


def _make_mock_db():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none = MagicMock(return_value=None)
    mock_result.scalars = MagicMock(
        return_value=MagicMock(all=MagicMock(return_value=[]))
    )
    mock_result.scalar_one = MagicMock(return_value=0)
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.add = MagicMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session.get = AsyncMock(return_value=None)
    mock_session.delete = AsyncMock()

    async def override():
        yield mock_session

    return mock_session, override


def _allow_override():
    def override():
        return {"sub": "admin-sub", "roles": ["admin"]}

    return override


def _deny_override():
    def override():
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Permission denied.")

    return override


class TestListResourceTypes:
    @pytest.mark.asyncio
    async def test_returns_all_resource_types_and_actions(self):
        """GET /api/v1/policy/resource-types returns JSON array with resource_type and actions for all entries in ResourceTypeManifest."""
        app = create_app()
        _, db_dep = _make_mock_db()
        app.dependency_overrides[get_db] = db_dep
        app.dependency_overrides[require_permission(RT_ROLE, "read")] = _allow_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/policy/resource-types")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == len(ResourceTypeManifest)

        returned_types = {item["resource_type"] for item in data}
        assert returned_types == set(ResourceTypeManifest.keys())

        for item in data:
            assert "resource_type" in item
            assert "actions" in item
            assert isinstance(item["actions"], list)
            expected_actions = ResourceTypeManifest[item["resource_type"]]["actions"]
            assert sorted(item["actions"]) == sorted(expected_actions)

    @pytest.mark.asyncio
    async def test_requires_authentication(self):
        """GET /api/v1/policy/resource-types returns 401 for unauthenticated callers."""
        app = create_app()
        _, db_dep = _make_mock_db()
        app.dependency_overrides[get_db] = db_dep
        # No auth bypass — real middleware rejects requests without a valid JWT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get("/api/v1/policy/resource-types")

        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_requires_role_read_permission(self):
        """GET /api/v1/policy/resource-types returns 403 for callers without role:read."""
        app = create_app()
        _, db_dep = _make_mock_db()
        app.dependency_overrides[get_db] = db_dep
        app.dependency_overrides[require_permission(RT_ROLE, "read")] = _deny_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get("/api/v1/policy/resource-types")

        assert response.status_code == 403


class TestGetRoleWithPolicies:
    @pytest.mark.asyncio
    async def test_get_role_includes_policy_statements(self, test_engine):
        """GET /api/v1/user-roles/{id} returns policy_statements array with actions, resources, and tag_conditions."""
        from app.db.models.identity import Role
        from app.db.models.policy_statement import PolicyStatement
        from app.db.models.policy_action import PolicyAction
        from app.db.models.policy_resource import PolicyResource
        from app.db.models.policy_tag_condition import PolicyTagCondition

        TestSession = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        role_id = uuid.uuid4()
        async with TestSession() as session:
            role = Role(id=role_id, name=f"test-get-policies-{role_id}", description="d")
            session.add(role)
            await session.flush()

            stmt1 = PolicyStatement(role_id=role.id, effect="allow", module="agent")
            session.add(stmt1)
            await session.flush()
            session.add(PolicyAction(policy_statement_id=stmt1.id, action="read"))
            session.add(PolicyAction(policy_statement_id=stmt1.id, action="execute"))
            session.add(PolicyResource(
                policy_statement_id=stmt1.id,
                resource_type="agent",
                resource_id="agent-123",
            ))
            session.add(PolicyTagCondition(
                policy_statement_id=stmt1.id, tag_key="env", tag_value="prod"
            ))

            stmt2 = PolicyStatement(role_id=role.id, effect="deny", module="role")
            session.add(stmt2)
            await session.flush()
            session.add(PolicyAction(policy_statement_id=stmt2.id, action="manage"))
            await session.commit()

        app = create_app()

        async def get_test_db():
            async with TestSession() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "read")] = _allow_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/api/v1/user-roles/{role_id}")

        assert response.status_code == 200
        data = response.json()

        # Verify top-level role fields
        assert data["id"] == str(role_id)
        assert data["name"] == f"test-get-policies-{role_id}"

        # Critical: policy_statements field must exist and be non-empty
        assert "policy_statements" in data, "GET /user-roles/{id} must return policy_statements field"
        stmts = data["policy_statements"]
        assert len(stmts) == 2, f"Expected 2 policy statements, got {len(stmts)}"

        # Find the allow/agent statement
        allow_stmt = next((s for s in stmts if s["effect"] == "allow"), None)
        assert allow_stmt is not None
        assert allow_stmt["module"] == "agent"

        # Verify actions are nested
        action_names = [a["action"] for a in allow_stmt["actions"]]
        assert "read" in action_names
        assert "execute" in action_names

        # Critical: resources must be present with resource_type and resource_id
        assert len(allow_stmt["resources"]) == 1
        assert allow_stmt["resources"][0]["resource_type"] == "agent"
        assert allow_stmt["resources"][0]["resource_id"] == "agent-123"

        # Critical: tag_conditions must be present
        assert len(allow_stmt["tag_conditions"]) == 1
        assert allow_stmt["tag_conditions"][0]["tag_key"] == "env"
        assert allow_stmt["tag_conditions"][0]["tag_value"] == "prod"

        # Find the deny/role statement
        deny_stmt = next((s for s in stmts if s["effect"] == "deny"), None)
        assert deny_stmt is not None
        assert deny_stmt["module"] == "role"
        assert len(deny_stmt["resources"]) == 0
        assert len(deny_stmt["tag_conditions"]) == 0

    @pytest.mark.asyncio
    async def test_get_role_returns_404_for_nonexistent_id(self):
        """GET /api/v1/user-roles/{id} returns 404 when role does not exist."""
        _, db_dep = _make_mock_db()

        app = create_app()
        app.dependency_overrides[get_db] = db_dep
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "read")] = _allow_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.get(f"/api/v1/user-roles/{uuid.uuid4()}")

        assert response.status_code == 404


class TestUpdatePolicyStatement:
    @pytest.mark.asyncio
    async def test_update_policy_statement(self, test_engine):
        """PATCH /api/v1/user-roles/{role_id}/policies/{policy_id} updates actions and resources."""
        from app.db.models.identity import Role
        from app.db.models.policy_statement import PolicyStatement
        from app.db.models.policy_action import PolicyAction
        from app.db.models.policy_resource import PolicyResource

        TestSession = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        role_id = uuid.uuid4()
        policy_id = uuid.uuid4()
        async with TestSession() as session:
            role = Role(id=role_id, name=f"test-update-stmt-{role_id}", description="d")
            session.add(role)
            await session.flush()

            stmt = PolicyStatement(id=policy_id, role_id=role.id, effect="allow", module="agent")
            session.add(stmt)
            await session.flush()
            session.add(PolicyAction(policy_statement_id=stmt.id, action="read"))
            session.add(PolicyResource(
                policy_statement_id=stmt.id,
                resource_type="agent",
                resource_id="old-resource",
            ))
            await session.commit()

        app = create_app()

        async def get_test_db():
            async with TestSession() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _allow_override()
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "read")] = _allow_override()

        updated_payload = {
            "effect": "deny",
            "module": "agent",
            "actions": [{"action": "execute"}, {"action": "delete"}],
            "resources": [{"resource_type": "agent", "resource_id": "new-resource-456"}],
            "tag_conditions": [],
        }

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                patch_response = await client.patch(
                    f"/api/v1/user-roles/{role_id}/policies/{policy_id}",
                    json=updated_payload,
                )

        assert patch_response.status_code == 200
        patch_data = patch_response.json()
        assert patch_data["effect"] == "deny"
        assert patch_data["module"] == "agent"

        # Old action gone, new actions present
        action_names = [a["action"] for a in patch_data["actions"]]
        assert "read" not in action_names, "Old action 'read' should be replaced"
        assert "execute" in action_names
        assert "delete" in action_names

        # Old resource replaced by new one
        assert len(patch_data["resources"]) == 1
        assert patch_data["resources"][0]["resource_id"] == "new-resource-456"

    @pytest.mark.asyncio
    async def test_update_policy_statement_reflected_in_get_role(self, test_engine):
        """After PATCH, GET /user-roles/{id} returns the updated policy_statements."""
        from app.db.models.identity import Role
        from app.db.models.policy_statement import PolicyStatement
        from app.db.models.policy_action import PolicyAction

        TestSession = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        role_id = uuid.uuid4()
        policy_id = uuid.uuid4()
        async with TestSession() as session:
            role = Role(id=role_id, name=f"test-patch-get-{role_id}", description="d")
            session.add(role)
            await session.flush()

            stmt = PolicyStatement(id=policy_id, role_id=role.id, effect="allow", module="user")
            session.add(stmt)
            await session.flush()
            session.add(PolicyAction(policy_statement_id=stmt.id, action="read"))
            await session.commit()

        app = create_app()

        async def get_test_db():
            async with TestSession() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _allow_override()
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "read")] = _allow_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # PATCH the policy
                await client.patch(
                    f"/api/v1/user-roles/{role_id}/policies/{policy_id}",
                    json={
                        "effect": "deny",
                        "module": "user",
                        "actions": [{"action": "delete"}],
                        "resources": [],
                        "tag_conditions": [],
                    },
                )
                # GET the role and verify updated policy_statements
                get_response = await client.get(f"/api/v1/user-roles/{role_id}")

        assert get_response.status_code == 200
        data = get_response.json()
        stmts = data["policy_statements"]
        assert len(stmts) == 1
        assert stmts[0]["effect"] == "deny"
        action_names = [a["action"] for a in stmts[0]["actions"]]
        assert action_names == ["delete"], f"Expected ['delete'], got {action_names}"

    @pytest.mark.asyncio
    async def test_update_policy_statement_returns_404_for_wrong_role(self, test_engine):
        """PATCH returns 404 when policy_id belongs to a different role."""
        from app.db.models.identity import Role
        from app.db.models.policy_statement import PolicyStatement
        from app.db.models.policy_action import PolicyAction

        TestSession = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        role_a_id = uuid.uuid4()
        role_b_id = uuid.uuid4()
        policy_id = uuid.uuid4()
        async with TestSession() as session:
            role_a = Role(id=role_a_id, name=f"role-a-{role_a_id}", description="a")
            role_b = Role(id=role_b_id, name=f"role-b-{role_b_id}", description="b")
            session.add_all([role_a, role_b])
            await session.flush()

            # policy belongs to role_a
            stmt = PolicyStatement(id=policy_id, role_id=role_a.id, effect="allow", module="agent")
            session.add(stmt)
            await session.flush()
            session.add(PolicyAction(policy_statement_id=stmt.id, action="read"))
            await session.commit()

        app = create_app()

        async def get_test_db():
            async with TestSession() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _allow_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                # Try to update policy via role_b — should fail
                response = await client.patch(
                    f"/api/v1/user-roles/{role_b_id}/policies/{policy_id}",
                    json={
                        "effect": "deny",
                        "module": "agent",
                        "actions": [{"action": "read"}],
                        "resources": [],
                        "tag_conditions": [],
                    },
                )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_policy_statement_requires_manage_permission(self):
        """PATCH /api/v1/user-roles/{role_id}/policies/{policy_id} returns 403 without role:manage."""
        _, db_dep = _make_mock_db()

        app = create_app()
        app.dependency_overrides[get_db] = db_dep
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _deny_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.patch(
                    f"/api/v1/user-roles/{uuid.uuid4()}/policies/{uuid.uuid4()}",
                    json={
                        "effect": "allow",
                        "module": "agent",
                        "actions": [{"action": "read"}],
                        "resources": [],
                        "tag_conditions": [],
                    },
                )

        assert response.status_code == 403


class TestCloneRole:
    @pytest.mark.asyncio
    async def test_clone_returns_201_with_new_role(self, test_engine):
        """Successful clone returns 201 with PermRoleRead body containing the new role's name."""
        from app.db.models.identity import Role

        TestSession = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        source_id = uuid.uuid4()
        source_name = f"source-role-{source_id}"
        async with TestSession() as session:
            source = Role(id=source_id, name=source_name, description="Original desc")
            session.add(source)
            await session.commit()
            await session.refresh(source)

        app = create_app()

        async def get_test_db():
            async with TestSession() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _allow_override()

        clone_name = f"clone-{source_id}"
        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/user-roles/{source_id}/clone",
                    json={"name": clone_name},
                )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == clone_name

    @pytest.mark.asyncio
    async def test_clone_creates_new_role_with_copied_statements(self, test_engine):
        """POST clone creates a new role and deep-copies all policy statements."""
        from app.db.models.identity import Role
        from app.db.models.policy_statement import PolicyStatement
        from app.db.models.policy_action import PolicyAction
        from sqlalchemy import select

        TestSession = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        source_id = uuid.uuid4()
        async with TestSession() as session:
            source = Role(id=source_id, name=f"src-stmts-{source_id}", description="d")
            session.add(source)
            await session.flush()
            stmt = PolicyStatement(
                role_id=source.id,
                effect="allow",
                module="agent",
            )
            session.add(stmt)
            await session.flush()
            session.add(PolicyAction(policy_statement_id=stmt.id, action="read"))
            await session.commit()

        app = create_app()

        async def get_test_db():
            async with TestSession() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _allow_override()

        clone_name = f"clone-stmts-{source_id}"
        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/user-roles/{source_id}/clone",
                    json={"name": clone_name},
                )

        assert response.status_code == 201
        new_role_id = uuid.UUID(response.json()["id"])

        # Verify clone has same number of statements as source
        async with TestSession() as session:
            cloned_stmts = (
                await session.execute(
                    select(PolicyStatement).where(
                        PolicyStatement.role_id == new_role_id
                    )
                )
            ).scalars().all()
            assert len(cloned_stmts) == 1
            assert cloned_stmts[0].module == "agent"
            assert cloned_stmts[0].effect == "allow"
            # Source statements unchanged
            src_stmts = (
                await session.execute(
                    select(PolicyStatement).where(
                        PolicyStatement.role_id == source_id
                    )
                )
            ).scalars().all()
            assert len(src_stmts) == 1

    @pytest.mark.asyncio
    async def test_clone_returns_409_on_duplicate_name(self):
        """POST /api/v1/user-roles/{id}/clone returns 409 when the target name already exists."""
        source_id = uuid.uuid4()

        # Source role found
        mock_source = MagicMock()
        mock_source.id = source_id
        mock_source.name = "Original"
        mock_source.description = "desc"

        # Duplicate exists
        mock_existing = MagicMock()
        mock_dup_result = MagicMock()
        mock_dup_result.scalar_one_or_none = MagicMock(return_value=mock_existing)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=mock_source)
        mock_session.execute = AsyncMock(return_value=mock_dup_result)

        async def override():
            yield mock_session

        app = create_app()
        app.dependency_overrides[get_db] = override
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _allow_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/user-roles/{source_id}/clone",
                    json={"name": "Duplicate Name"},
                )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_clone_returns_404_when_source_not_found(self):
        """POST /api/v1/user-roles/{id}/clone returns 404 when the source role does not exist."""
        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=None)  # Source not found

        async def override():
            yield mock_session

        app = create_app()
        app.dependency_overrides[get_db] = override
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _allow_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/user-roles/{uuid.uuid4()}/clone",
                    json={"name": "Any Name"},
                )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_clone_requires_role_manage_permission(self):
        """POST /api/v1/user-roles/{id}/clone returns 403 for callers without role:manage."""
        _, db_dep = _make_mock_db()

        app = create_app()
        app.dependency_overrides[get_db] = db_dep
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _deny_override()

        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/user-roles/{uuid.uuid4()}/clone",
                    json={"name": "Any Name"},
                )

        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_clone_inherits_description_from_source_when_not_provided(
        self, test_engine
    ):
        """When description is omitted in body, clone inherits description from source role."""
        from app.db.models.identity import Role

        TestSession = async_sessionmaker(
            bind=test_engine, class_=AsyncSession, expire_on_commit=False
        )

        source_id = uuid.uuid4()
        original_description = "Original role description"
        async with TestSession() as session:
            source = Role(
                id=source_id,
                name=f"src-desc-{source_id}",
                description=original_description,
            )
            session.add(source)
            await session.commit()

        app = create_app()

        async def get_test_db():
            async with TestSession() as s:
                try:
                    yield s
                    await s.commit()
                except Exception:
                    await s.rollback()
                    raise

        app.dependency_overrides[get_db] = get_test_db
        app.dependency_overrides[require_permission(RT_PERMISSIONS, "manage")] = _allow_override()

        clone_name = f"clone-desc-{source_id}"
        with _bypass_auth():
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    f"/api/v1/user-roles/{source_id}/clone",
                    json={"name": clone_name},  # No description provided
                )

        assert response.status_code == 201
        data = response.json()
        assert data["description"] == original_description
