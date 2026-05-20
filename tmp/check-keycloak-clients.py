#!/usr/bin/env python3
"""Check Keycloak client configuration in both realms."""
import requests

# Get admin token
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

# List clients in agent realm
print("=" * 80)
print("AGENT REALM (ai_agents) CLIENTS")
print("=" * 80)
clients_resp = requests.get(
    'http://localhost:8082/admin/realms/ai_agents/clients',
    headers={'Authorization': f'Bearer {token}'}
)

for client in clients_resp.json():
    if 'parthenon' in client.get('clientId', '').lower():
        print(f"Client ID: {client['clientId']}")
        print(f"  UUID: {client['id']}")
        print(f"  Enabled: {client.get('enabled', False)}")
        print(f"  Public: {client.get('publicClient', False)}")
        print(f"  Protocol: {client.get('protocol', 'N/A')}")
        print()

# Also check human realm for comparison
print("=" * 80)
print("HUMAN REALM (parthenon) CLIENTS")
print("=" * 80)
clients_resp2 = requests.get(
    'http://localhost:8082/admin/realms/parthenon/clients',
    headers={'Authorization': f'Bearer {token}'}
)

for client in clients_resp2.json():
    if 'parthenon' in client.get('clientId', '').lower():
        print(f"Client ID: {client['clientId']}")
        print(f"  UUID: {client['id']}")
        print(f"  Enabled: {client.get('enabled', False)}")
        print(f"  Public: {client.get('publicClient', False)}")
        print(f"  Protocol: {client.get('protocol', 'N/A')}")
        print()

# Check backend settings
print("=" * 80)
print("BACKEND CONFIGURATION")
print("=" * 80)
import sys
sys.path.insert(0, 'backend')
from app.core.config import get_settings

settings = get_settings()
print(f"JWT Audience (expected client_id): {settings.jwt_audience}")
print()
