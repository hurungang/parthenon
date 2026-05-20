#!/usr/bin/env python3
"""Verify agent client fix is complete."""
import sys
sys.path.insert(0, 'backend')
import requests
from app.services.agents.identity_service import _agent_realm_client_id

expected_client = _agent_realm_client_id()
print(f'Backend expects agent client: "{expected_client}"')
print()

# Check if it exists in Keycloak
token_resp = requests.post(
    'http://localhost:8082/realms/master/protocol/openid-connect/token',
    data={
        'client_id': 'admin-cli',
        'username': 'admin',
        'password': 'admin',
        'grant_type': 'password'
    }
)
token = token_resp.json()['access_token']

clients_resp = requests.get(
    'http://localhost:8082/admin/realms/ai_agents/clients',
    headers={'Authorization': f'Bearer {token}'}
)

client_ids = [c.get('clientId') for c in clients_resp.json()]
print(f'Clients in agent realm: {[c for c in client_ids if "parthenon" in c.lower()]}')
print()

if expected_client in client_ids:
    print(f'✅ Client "{expected_client}" EXISTS in agent realm!')
    print()
    print('=' * 70)
    print('SUCCESS! Agent identity sign-in should now work.')
    print('=' * 70)
else:
    print(f'❌ Client "{expected_client}" NOT FOUND in agent realm.')
    print(f'Available clients: {client_ids}')
