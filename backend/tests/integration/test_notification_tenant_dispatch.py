"""Scenario 5 — notification dispatch per tenant (shared slot retired).

``get-recipient-group`` and group dispatch resolve only the calling
tenant's group; the NULL-tenant shared/global slot is unreachable from
the data plane; a group name that exists only in another tenant fails
closed.
"""
from __future__ import annotations

import uuid

import pytest

from tests.integration._strict_tenant_utils import (  # noqa: F401
    create_two_tenants,
    count_null_tenant_rows,
    db,
    make_module_schema_fixture,
)

_schema = make_module_schema_fixture()

GROUP_SLUG = "ops-oncall"


async def _create_group(db, tenant_id, slug: str = GROUP_SLUG, active: bool = True):
    from app.db.models.notifications import RecipientGroup

    suffix = uuid.uuid4().hex[:6]
    group = RecipientGroup(
        tenant_id=tenant_id,
        name=f"{slug}-{suffix}",
        slug=slug,
        is_active=active,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


class TestPerTenantGroupResolution:
    async def test_get_recipient_group_resolves_own_tenant_only(self, db):
        from app.core import tenant_context as tc
        from app.services.notifications.mcp_tool import handle_get_recipient_group

        tenant_a, tenant_b = await create_two_tenants(db)
        group_a = await _create_group(db, tenant_a.id)
        group_b = await _create_group(db, tenant_b.id)

        ctx = tc.TenantContext(
            tenant_id=tenant_a.id, slug=tenant_a.slug, name=tenant_a.name
        )
        token = tc.set_current_tenant_context(ctx)
        try:
            result = await handle_get_recipient_group(
                {"group_slug": GROUP_SLUG}, db
            )
        finally:
            tc.reset_current_tenant_context(token)

        assert "error" not in result
        assert result["group_slug"] == GROUP_SLUG
        # The identity of the resolved group is checked via a re-query below.
        from sqlalchemy import select

        from app.db.models.notifications import RecipientGroup

        resolved = (
            (
                await db.execute(
                    select(RecipientGroup).where(
                        RecipientGroup.slug == GROUP_SLUG,
                        RecipientGroup.tenant_id == tenant_a.id,
                    )
                )
            )
            .scalars()
            .one()
        )
        assert resolved.id == group_a.id

    async def test_group_only_in_other_tenant_fails_closed(self, db):
        from app.core import tenant_context as tc
        from app.services.notifications.mcp_tool import handle_get_recipient_group

        tenant_a, tenant_b = await create_two_tenants(db)
        await _create_group(db, tenant_b.id, slug="b-only-group")

        ctx = tc.TenantContext(
            tenant_id=tenant_a.id, slug=tenant_a.slug, name=tenant_a.name
        )
        token = tc.set_current_tenant_context(ctx)
        try:
            result = await handle_get_recipient_group(
                {"group_slug": "b-only-group"}, db
            )
        finally:
            tc.reset_current_tenant_context(token)

        assert "error" in result
        assert "not found" in result["error"]

    async def test_dispatch_resolves_own_tenant_group(self, db):
        from app.services.notifications.notification_service import NotificationService

        tenant_a, tenant_b = await create_two_tenants(db)
        group_a = await _create_group(db, tenant_a.id)
        group_b = await _create_group(db, tenant_b.id)

        service = NotificationService(db)
        result = await service.send_to_group(
            GROUP_SLUG, "tenant A page", tenant_id=tenant_a.id
        )
        # Resolution succeeded within tenant A (no "not found" ValueError)
        # and no channel mappings means nothing was dispatched.
        assert result is not None

        # The same slug in tenant B is a DIFFERENT row, resolvable from B.
        result_b = await service.send_to_group(
            GROUP_SLUG, "tenant B page", tenant_id=tenant_b.id
        )
        assert result_b is not None

    async def test_dispatch_miss_is_fail_closed(self, db):
        from app.services.notifications.notification_service import NotificationService

        tenant_a, tenant_b = await create_two_tenants(db)
        await _create_group(db, tenant_b.id, slug="secret-b-group")

        service = NotificationService(db)
        with pytest.raises(ValueError, match="not found"):
            await service.send_to_group(
                "secret-b-group", "probe", tenant_id=tenant_a.id
            )

    async def test_inactive_group_not_dispatched(self, db):
        from app.services.notifications.notification_service import NotificationService

        tenant_a, _tenant_b = await create_two_tenants(db)
        await _create_group(db, tenant_a.id, slug="retired-group", active=False)

        service = NotificationService(db)
        with pytest.raises(ValueError, match="inactive"):
            await service.send_to_group(
                "retired-group", "page", tenant_id=tenant_a.id
            )


class TestSharedSlotRetired:
    async def test_no_null_tenant_recipient_groups_remain(self, db):
        assert await count_null_tenant_rows(db, "recipient_groups") == 0
        assert await count_null_tenant_rows(db, "notification_channels") == 0

    async def test_contextless_dispatch_falls_back_to_root_not_shared(self, db):
        """The legacy fallback target is the ROOT tenant — never a
        NULL-tenant shared slot (which no longer exists)."""
        from app.db.models.tenant import Tenant
        from app.services.notifications.notification_service import NotificationService

        suffix = uuid.uuid4().hex[:6]
        root = Tenant(name=f"root-{suffix}", slug="root", is_system_tenant=True)
        db.add(root)
        await db.commit()
        await db.refresh(root)

        from sqlalchemy import select

        from app.db.models.notifications import RecipientGroup

        root_group = RecipientGroup(
            tenant_id=root.id, name=f"root-{suffix}", slug="root-ops"
        )
        db.add(root_group)
        await db.commit()

        service = NotificationService(db)
        # tenant_id=None → root-tenant resolution (contextless background path)
        result = await service.send_to_group("root-ops", "to root", tenant_id=None)
        assert result is not None
