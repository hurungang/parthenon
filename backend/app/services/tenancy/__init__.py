"""Tenancy services — platform settings, tenant resolution, lifecycle, audit.

Multi-tenancy is opt-in and disabled by default.  All tenant feature code
branches on the cached ``multi_tenancy_enabled`` platform setting read
through :class:`~app.services.tenancy.platform_settings_service.PlatformSettingsService`;
when the switch is off every service in this package is inert.
"""
from app.services.tenancy.platform_settings_service import (
    MULTI_TENANCY_ENABLED_KEY,
    PlatformSettingsService,
    get_platform_settings_service,
)
from app.services.tenancy.tenant_audit_service import TenantAuditService

__all__ = [
    "MULTI_TENANCY_ENABLED_KEY",
    "PlatformSettingsService",
    "TenantAuditService",
    "get_platform_settings_service",
]
