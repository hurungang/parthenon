# Fix agent realm client mismatch by creating client matching config/identity.yaml.
import asyncio
import sys
sys.path.insert(0, 'backend')

from app.core.yaml_config import load_identity_yaml
from app.services.identity.keycloak_admin_client import KeycloakAdminClient


async def fix_agent_client():
    """Create the correct OAuth client in agent realm, matching identity.yaml."""
    kc_client = KeycloakAdminClient("http://localhost:8082")
    
    # Determine client ID from identity.yaml (must match what _agent_realm_client_id() returns)
    yaml_cfg = load_identity_yaml()
    agent_client_id = yaml_cfg.audience or "parthenon"
    print(f"Using agent client ID '{agent_client_id}' from identity.yaml")
    print()
    
    # Get admin token
    print("Authenticating with Keycloak...")
    admin_token = await kc_client.authenticate("admin", "admin")
    print("✓ Authenticated")
    print()
    
    # Check if agent client already exists
    print(f"Checking for '{agent_client_id}' client in ai_agents realm...")
    exists = await kc_client.client_exists(admin_token, "ai_agents", agent_client_id)
    
    if exists:
        print(f"✓ Client '{agent_client_id}' already exists")
    else:
        print(f"Creating '{agent_client_id}' client in ai_agents realm...")
        await kc_client.create_oidc_client(
            admin_token,
            "ai_agents",
            agent_client_id,
            redirect_uris=[
                "http://localhost:8000/api/v1/agents/oauth/callback",
                "http://localhost:5173/agents/identities/oauth/callback",
                "http://localhost:4173/agents/identities/oauth/callback",
                "http://localhost:3000/agents/identities/oauth/callback",
            ],
            public_client=True
        )
        print(f"✓ Created client '{agent_client_id}' in agent realm")
    
    print()
    print("=" * 70)
    print(f"✓ Agent realm client '{agent_client_id}' verified!")
    print("=" * 70)
    print()
    print(f"The agent realm has the '{agent_client_id}' client that the backend expects.")
    print()


if __name__ == "__main__":
    asyncio.run(fix_agent_client())
