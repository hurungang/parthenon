"""Consolidated Parthenon environment setup CLI.

Replaces the collection of ad-hoc scripts in ``scripts/`` with a single
entry point covering all bootstrapping needs:

    identity      Provision Keycloak realm, clients, roles, admin user
    database      Seed system roles, permissions, skills, system tools
    certificates  Bootstrap the certificate authority
    dev           Full local development bootstrap (all of the above)
    verify        Check current state of all components without changes

Usage:
    python -m setup.main <sub-command> [--help]
    python -m setup.main dev --output json
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import sys
from pathlib import Path

# Fix Unicode print on Windows terminals
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")  # type: ignore[assignment]
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")  # type: ignore[assignment]

# Ensure backend code is importable
_BACKEND_DIR = Path(__file__).parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Load .env before any settings access
from dotenv import load_dotenv
load_dotenv(_BACKEND_DIR / ".env", override=False)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("setup")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m setup.main",
        description="Parthenon environment setup tool — bootstraps identity, database, and certificates.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── identity ────────────────────────────────────────────────────
    id_cmd = sub.add_parser(
        "identity",
        help="Provision Keycloak realm and clients",
        description="Provision Keycloak user and agent realms, OIDC clients, admin user.",
    )
    id_cmd.add_argument(
        "--external",
        action="store_true",
        help="Register an external OIDC provider instead of bundled Keycloak.",
    )
    id_cmd.add_argument(
        "--keycloak-url",
        default=None,
        help="Keycloak base URL (default: http://localhost:8082).",
    )
    id_cmd.add_argument(
        "--realm",
        default=None,
        help="Keycloak realm name (default: parthenon).",
    )
    id_cmd.add_argument(
        "--client-id",
        default=None,
        help="OIDC client ID (default: parthenon-api).",
    )
    id_cmd.add_argument(
        "--admin-user",
        default=None,
        help="Keycloak master-realm admin username.",
    )
    id_cmd.add_argument(
        "--admin-password",
        default=None,
        help="Keycloak master-realm admin password.",
    )
    id_cmd.add_argument(
        "--initial-admin-password",
        default=None,
        help="Password for the initial Parthenon admin user.",
    )
    id_cmd.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )

    # ── database ────────────────────────────────────────────────────
    db_cmd = sub.add_parser(
        "database",
        help="Seed database with system roles, permissions, skills, tools",
        description="Idempotently seeds system roles, permissions, skills, and system tools.",
    )
    db_cmd.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    db_cmd.add_argument(
        "--admin-email",
        default=None,
        help="Email of admin user to assign system_admin role to (requires existing platform user).",
    )

    # ── certificates ────────────────────────────────────────────────
    cert_cmd = sub.add_parser(
        "certificates",
        help="Bootstrap the certificate authority",
        description="Generate (or load) the root CA certificate used for mTLS.",
    )
    cert_cmd.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )

    # ── dev ──────────────────────────────────────────────────────────
    dev_cmd = sub.add_parser(
        "dev",
        help="Full local development environment bootstrap",
        description=(
            "Run identity → database → certificates in dependency order. "
            "Replicates the behavior of the deprecated scripts/init-local-dev.py."
        ),
    )
    dev_cmd.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )

    # ── verify ──────────────────────────────────────────────────────
    verify_cmd = sub.add_parser(
        "verify",
        help="Check current state of all components without making changes",
        description="Read-only check: reports what is and is not configured.",
    )
    verify_cmd.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    command = args.command

    try:
        if command == "identity":
            from setup.identity import run_identity_setup
            exit_code = asyncio.run(run_identity_setup(args))
        elif command == "database":
            from setup.database import run_database_setup
            exit_code = asyncio.run(run_database_setup(args))
        elif command == "certificates":
            from setup.certificates import run_certificates_setup
            exit_code = asyncio.run(run_certificates_setup(args))
        elif command == "dev":
            from setup.dev import run_dev_setup
            exit_code = asyncio.run(run_dev_setup(args))
        elif command == "verify":
            from setup.verify import run_verify
            exit_code = asyncio.run(run_verify(args))
        else:
            parser.print_help()
            exit_code = 1
    except KeyboardInterrupt:
        print("\nSetup cancelled by user.")
        exit_code = 1
    except Exception:
        logger.exception("Setup failed with unexpected error")
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
