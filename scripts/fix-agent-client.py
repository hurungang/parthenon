#!/usr/bin/env python3
"""Fix agent realm client mismatch by creating 'parthenon' client."""
import asyncio
import sys
sys.path.insert(0, 'backend')

from app.services.identity.keycloak_admin_client import KeycloakAdminClient


async def fix_agent_client():
    """Create the correct 'parthenon' client in agent realm."""
    kc_client = KeycloakAdminClient("http://localhost:8082")
    
    # Get admin token
    print("Authenticating with Keycloak...")
    admin_token = await kc_client.authenticate("admin", "admin")
    print("✓ Authenticated")
    print()
    
    # Check if 'parthenon' client already exists
    print("Checking for 'parthenon' client in ai_agents realm...")
    exists = await kc_client.client_exists(admin_token, "ai_agents", "parthenon")
    
    if exists:
        print("✓ Client 'parthenon' already exists")
    else:
        print("Creating 'parthenon' client in ai_agents realm...")
        await kc_client.create_oidc_client(
            admin_token,
            "ai_agents",
            "parthenon",
            redirect_uris=[
                "http://localhost:8000/api/v1/agents/oauth/callback",
                "http://localhost:5173/agents/identities/oauth/callback",
                "http://localhost:4173/agents/identities/oauth/callback",
                "http://localhost:3000/agents/identities/oauth/callback",
            ],
            public_client=True
        )
        print("✓ Created client 'parthenon' in agent realm")
    
    print()
    print("=" * 70)
    print("✓ Agent realm client fixed!")
    print("=" * 70)
    print()
    print("The agent realm now has the 'parthenon' client that the backend expects.")
    print("Note: The old 'parthenon-api' client still exists but won't interfere.")
    print()


if __name__ == "__main__":
    asyncio.run(fix_agent_client())
