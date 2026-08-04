"""Unit tests for API Key admin CRUD API.

Tests the schemas and business logic without requiring a running server.
Uses pytest fixtures for clean test isolation.
"""
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyListItem,
    ApiKeyRead,
    ApiKeyRevokeResponse,
    ApiKeyValidateRequest,
    ApiKeyValidateResponse,
    IdentityWithRoles,
    RoleItem,
    SkillWithVersion,
    ToolDefinition,
)


class TestApiKeyCreateSchema:
    """Test ApiKeyCreate Pydantic validation."""

    def test_valid_create_schema(self):
        data = ApiKeyCreate(
            name="Test Key",
            agent_identity_id=uuid.uuid4(),
            agent_role_id=uuid.uuid4(),
        )
        assert data.name == "Test Key"
        assert isinstance(data.agent_identity_id, uuid.UUID)
        assert isinstance(data.agent_role_id, uuid.UUID)

    def test_name_too_short(self):
        with pytest.raises(ValidationError):
            ApiKeyCreate(
                name="",
                agent_identity_id=uuid.uuid4(),
                agent_role_id=uuid.uuid4(),
            )

    def test_name_too_long(self):
        with pytest.raises(ValidationError):
            ApiKeyCreate(
                name="x" * 129,
                agent_identity_id=uuid.uuid4(),
                agent_role_id=uuid.uuid4(),
            )

    def test_name_max_length(self):
        data = ApiKeyCreate(
            name="x" * 128,
            agent_identity_id=uuid.uuid4(),
            agent_role_id=uuid.uuid4(),
        )
        assert len(data.name) == 128


class TestApiKeyCreateResponseSchema:
    """Test ApiKeyCreateResponse schema."""

    def test_valid_response(self):
        now = datetime.now(timezone.utc)
        resp = ApiKeyCreateResponse(
            id=uuid.uuid4(),
            name="Test Key",
            key_prefix="phn_sk_",
            api_key="phn_sk_abc123def456ghi789jkl012mno345pq",
            agent_identity_id=uuid.uuid4(),
            agent_identity_name="Agent X",
            agent_role_id=uuid.uuid4(),
            agent_role_name="Developer",
            created_at=now,
        )
        assert resp.key_prefix == "phn_sk_"
        assert resp.api_key.startswith("phn_sk_")


class TestApiKeyListItemSchema:
    """Test ApiKeyListItem schema."""

    def test_valid_list_item(self):
        now = datetime.now(timezone.utc)
        item = ApiKeyListItem(
            id=uuid.uuid4(),
            name="Test Key",
            key_prefix="phn_sk_",
            agent_identity_id=uuid.uuid4(),
            agent_identity_name="Agent X",
            agent_role_id=uuid.uuid4(),
            agent_role_name="Developer",
            status="active",
            created_at=now,
            last_used_at=None,
        )
        assert item.status == "active"
        assert item.last_used_at is None


class TestApiKeyRevokeResponseSchema:
    """Test revoke response."""

    def test_revoke_response(self):
        resp = ApiKeyRevokeResponse(
            id=uuid.uuid4(),
            status="revoked",
            message="API key revoked successfully",
        )
        assert resp.status == "revoked"


class TestIdentityWithRolesSchema:
    """Test IdentityWithRoles dropdown schema."""

    def test_valid_identity_with_roles(self):
        data = IdentityWithRoles(
            identity_id=uuid.uuid4(),
            identity_name="Agent X",
            roles=[
                RoleItem(role_id=uuid.uuid4(), role_name="Developer"),
                RoleItem(role_id=uuid.uuid4(), role_name="Viewer"),
            ],
        )
        assert len(data.roles) == 2

    def test_empty_roles(self):
        data = IdentityWithRoles(
            identity_id=uuid.uuid4(),
            identity_name="Agent X",
            roles=[],
        )
        assert len(data.roles) == 0


class TestApiKeyValidateRequestSchema:
    """Test internal validation request."""

    def test_valid_request(self):
        req = ApiKeyValidateRequest(
            key_hash="abc123def4567890abc123def4567890abc123def4567890abc123def4567890",
        )
        assert len(req.key_hash) == 64

    def test_with_since(self):
        now = datetime.now(timezone.utc)
        req = ApiKeyValidateRequest(
            key_hash="abc123def4567890abc123def4567890abc123def4567890abc123def4567890",
            since=now,
        )
        assert req.since == now


class TestApiKeyValidateResponseSchema:
    """Test validation response."""

    def test_valid_response(self):
        resp = ApiKeyValidateResponse(
            valid=True,
            agent_identity_id=uuid.uuid4(),
            agent_role_id=uuid.uuid4(),
            identity_token="eyJ...",
            permissions=["server____tool1", "server____tool2"],
            skills=[],
        )
        assert resp.valid is True
        assert len(resp.permissions) == 2


class TestSkillWithVersionSchema:
    """Test SkillWithVersion schema."""

    def test_valid_skill(self):
        skill = SkillWithVersion(
            skill_id=uuid.uuid4(),
            name="my-skill",
            description="A test skill",
            is_active=True,
            updated_at=datetime.now(timezone.utc),
            tools=[
                ToolDefinition(
                    tool_id=uuid.uuid4(),
                    name="server____tool1",
                    description="Test tool",
                )
            ],
        )
        assert skill.name == "my-skill"
        assert len(skill.tools) == 1
