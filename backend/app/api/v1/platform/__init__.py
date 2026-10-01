"""Platform admin API — settings, tenants, and cross-tenant security audit.

Routers under ``/api/v1/platform/*`` are the platform admin console's
backend: tenant METADATA and platform configuration only — never tenant
business data.  All routes are hosted at the base domain (bypassed by
tenant resolution) and guarded by ``platform::*`` resource types via
``require_permission``.
"""
