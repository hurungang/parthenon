"""CLI entrypoint for the Parthenon backend.

Usage:
    python -m app.cli setup-identity --help

Sub-commands:
    setup-identity  Provision the identity provider (Keycloak or external OIDC).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


async def _run_setup_identity(args: argparse.Namespace) -> int:
    """Execute the identity bootstrap and return exit code 0/1."""
    from app.db.session import AsyncSessionLocal
    from app.schemas.identity_bootstrap import ProviderSetupRequest, ProviderType
    from app.services.identity.bootstrap_service import IdentityBootstrapService

    provider_type_str: str = args.provider_type
    try:
        provider_type = ProviderType(provider_type_str)
    except ValueError:
        logger.error(
            "Invalid --provider-type %r. Valid values: %s",
            provider_type_str,
            ", ".join(pt.value for pt in ProviderType),
        )
        return 1

    request = ProviderSetupRequest(
        provider_type=provider_type,
        keycloak_url=getattr(args, "keycloak_url", None),
        realm_name=getattr(args, "realm", None),
        client_id=getattr(args, "client_id", None),
        admin_user=getattr(args, "admin_user", None),
        admin_password=getattr(args, "admin_password", None),
        initial_admin_password=getattr(args, "initial_admin_password", None),
        client_secret=getattr(args, "client_secret", None),
        oidc_discovery_url=getattr(args, "external_oidc_url", None),
    )

    service = IdentityBootstrapService()
    async with AsyncSessionLocal() as db:
        try:
            if provider_type == ProviderType.KEYCLOAK_BUNDLED:
                result = await service.provision_bundled_keycloak(db, request)
            else:
                result = await service.provision_external_oidc(db, request)
        except Exception as exc:
            logger.error("Provisioning raised an unexpected error: %s", exc)
            return 1

    summary = {
        "success": result.success,
        "provider_type": result.provider_type,
        "oidc_provider_url": result.oidc_provider_url,
        "realm_name": result.realm_name,
        "client_id": result.client_id,
    }
    if not result.success:
        summary["error_code"] = result.error_code
        summary["detail"] = result.detail

    print(json.dumps(summary, indent=2))

    if result.success:
        logger.info("Identity provider setup complete.")
        return 0
    else:
        logger.error("Identity provider setup failed: %s", result.detail)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Parthenon CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ── setup-identity sub-command ──────────────────────────────────────
    setup = subparsers.add_parser(
        "setup-identity",
        help="Provision the identity provider.",
        description=(
            "Provision a bundled Keycloak instance or register an external OIDC provider.\n\n"
            "Examples:\n"
            "  Bundled Keycloak:\n"
            "    python -m app.cli setup-identity \\\n"
            "      --provider-type keycloak_bundled \\\n"
            "      --keycloak-url http://localhost:8082 \\\n"
            "      --realm parthenon \\\n"
            "      --client-id parthenon-api \\\n"
            "      --admin-user admin \\\n"
            "      --admin-password secret \\\n"
            "      --initial-admin-password adminpass\n\n"
            "  External OIDC / Azure EntraID:\n"
            "    python -m app.cli setup-identity \\\n"
            "      --provider-type keycloak_external \\\n"
            "      --external-oidc-url https://sso.example.com/realms/myapp/.well-known/openid-configuration \\\n"
            "      --client-id parthenon \\\n"
            "      --client-secret my-secret"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    setup.add_argument(
        "--provider-type",
        required=True,
        choices=[
            pt.value
            for pt in __import__(
                "app.schemas.identity_bootstrap", fromlist=["ProviderType"]
            ).ProviderType
        ],
        help="Identity provider type.",
    )
    setup.add_argument(
        "--keycloak-url", dest="keycloak_url", help="Base URL of the Keycloak instance."
    )
    setup.add_argument("--realm", dest="realm", help="Keycloak realm name.")
    setup.add_argument("--client-id", dest="client_id", help="OIDC client ID.")
    setup.add_argument(
        "--admin-user", dest="admin_user", help="Keycloak master-realm admin username."
    )
    setup.add_argument(
        "--admin-password", dest="admin_password", help="Keycloak master-realm admin password."
    )
    setup.add_argument(
        "--initial-admin-password",
        dest="initial_admin_password",
        help="Password for the initial Parthenon admin user created in the realm.",
    )
    setup.add_argument(
        "--client-secret", dest="client_secret", help="Pre-existing OIDC client secret."
    )
    setup.add_argument(
        "--external-oidc-url",
        dest="external_oidc_url",
        help="Full /.well-known/openid-configuration URL (external OIDC providers).",
    )

    return parser


def main() -> None:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "setup-identity":
        exit_code = asyncio.run(_run_setup_identity(args))
        sys.exit(exit_code)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
