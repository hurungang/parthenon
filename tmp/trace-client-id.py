#!/usr/bin/env python3
"""Trace through the actual code path for agent realm client ID."""
import sys
sys.path.insert(0, 'backend')

from app.core.config import get_settings
from app.services.agents.identity_service import _agent_realm_client_id

settings = get_settings()

print("Tracing _agent_realm_client_id():")
print(f"  settings.jwt_audience = '{settings.jwt_audience}'")
print(f"  base_client_id = settings.jwt_audience or 'parthenon-api'")
if settings.jwt_audience:
    print(f"  → base_client_id = '{settings.jwt_audience}'")
else:
    print(f"  → base_client_id = 'parthenon-api'")

print(f"  return f\"{{base_client_id}}\"")
result = _agent_realm_client_id()
print(f"  → result = '{result}'")
print()
print(f"Expected client in agent realm: '{result}'")
print(f"Actual client in agent realm: 'parthenon-api'")
print()
if result != "parthenon-api":
    print(f"❌ MISMATCH! Backend expects '{result}' but Keycloak has 'parthenon-api'")
else:
    print(f"✅ MATCH! Both are 'parthenon-api'")
