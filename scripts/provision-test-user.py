#!/usr/bin/env python3
"""
Provision or deprovision a test user in Keycloak for E2E testing.

Usage:
    python scripts/provision-test-user.py create <username> [password]
    python scripts/provision-test-user.py delete <username>
    python scripts/provision-test-user.py create-timestamp  # Creates user with timestamp suffix
"""
import asyncio
import sys
from datetime import datetime

# Add backend to path
sys.path.insert(0, "backend")

from app.services.identity.keycloak_admin_client import (
    KeycloakAdminClient,
    KeycloakAdminError,
)


async def create_user(
    username: str, password: str, keycloak_url: str = "http://localhost:8082"
) -> None:
    """Create a test user with no permissions."""
    client = KeycloakAdminClient(keycloak_url)

    try:
        # Authenticate as admin
        token = await client.authenticate("admin", "admin")
        print(f"✓ Authenticated to Keycloak")

        # Create user in parthenon realm (user realm)
        await client.create_user(
            token=token,
            realm_name="parthenon",
            username=username,
            password=password,
            roles=None,  # No roles = no permissions
        )
        print(f"✓ Created user '{username}' with password '{password}'")
        print(f"  Realm: parthenon")
        print(f"  Roles: none (no permissions)")

    except KeycloakAdminError as e:
        print(f"✗ Failed to create user: {e.error_code} - {e.detail}", file=sys.stderr)
        sys.exit(1)


async def delete_user(
    username: str, keycloak_url: str = "http://localhost:8082"
) -> None:
    """Delete a test user."""
    client = KeycloakAdminClient(keycloak_url)

    try:
        # Authenticate as admin
        token = await client.authenticate("admin", "admin")
        print(f"✓ Authenticated to Keycloak")

        # Delete user from parthenon realm
        deleted = await client.delete_user(
            token=token, realm_name="parthenon", username=username
        )

        if deleted:
            print(f"✓ Deleted user '{username}' from realm 'parthenon'")
        else:
            print(f"ℹ User '{username}' not found in realm 'parthenon'")

    except KeycloakAdminError as e:
        print(f"✗ Failed to delete user: {e.error_code} - {e.detail}", file=sys.stderr)
        sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "create":
        if len(sys.argv) < 3:
            print("Usage: provision-test-user.py create <username> [password]")
            sys.exit(1)
        username = sys.argv[2]
        password = sys.argv[3] if len(sys.argv) > 3 else username
        asyncio.run(create_user(username, password))

    elif command == "delete":
        if len(sys.argv) < 3:
            print("Usage: provision-test-user.py delete <username>")
            sys.exit(1)
        username = sys.argv[2]
        asyncio.run(delete_user(username))

    elif command == "create-timestamp":
        # Create user with timestamp suffix
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        username = f"testuser_{timestamp}"
        password = "testpass123"
        print(f"Creating timestamped test user: {username}")
        asyncio.run(create_user(username, password))
        # Print just the username for scripts to capture
        print(f"\nUSERNAME={username}")

    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
