#!/usr/bin/env python3
"""Simple test of get_settings() with fresh import."""
# Clear any cached settings
import sys
sys.path.insert(0, 'backend')

# Clear the lru_cache on get_settings if it exists
from app.core import config
if hasattr(config.get_settings, 'cache_clear'):
    config.get_settings.cache_clear()

# Now get fresh settings
from app.core.config import get_settings
settings = get_settings()

print(f"jwt_audience: {settings.jwt_audience}")
print(f"oidc_provider_url: {settings.oidc_provider_url}")
print(f"identity_provider_type: {settings.identity_provider_type}")

# Also test the agent realm client ID function
from app.services.agents.identity_service import _agent_realm_client_id
print(f"_agent_realm_client_id(): {_agent_realm_client_id()}")
