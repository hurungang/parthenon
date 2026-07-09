"""Full local development bootstrap — runs identity → database → certificates.

Replicates the behavior of the deprecated ``scripts/init-local-dev.py``.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any

logger = logging.getLogger("setup.dev")


async def run_dev_setup(args: Any) -> int:
    """Run full local development bootstrap in dependency order."""
    print("=" * 80)
    print("PARTHENON LOCAL DEVELOPMENT SETUP")
    print("=" * 80)
    print()

    if args.output == "json":
        all_results: list[dict[str, object]] = []
    else:
        all_results = []

    exit_code = 0

    # Step 1: Identity (Keycloak provisioning)
    print("--- Step 1: Identity Provider (Keycloak) ---")
    try:
        import argparse as ap
        id_args = ap.Namespace(
            external=False,
            keycloak_url=os.environ.get("KEYCLOAK_URL", None),
            realm=os.environ.get("KEYCLOAK_REALM", None),
            client_id=os.environ.get("KEYCLOAK_CLIENT_ID", None),
            admin_user=os.environ.get("KEYCLOAK_ADMIN_USER", None),
            admin_password=os.environ.get("KEYCLOAK_ADMIN_PASSWORD", None),
            initial_admin_password=os.environ.get("INITIAL_ADMIN_PASSWORD", None),
            output=args.output,
        )
        from setup.identity import run_identity_setup
        rc = await run_identity_setup(id_args)
        if rc != 0:
            exit_code = rc
            print("  ⚠ Identity setup completed with errors")
        print()
    except Exception as exc:
        logger.exception("Identity setup failed")
        exit_code = 1
        print(f"  ✗ Identity setup error: {exc}")
        print()

    # Step 2: Database (seed)
    print("--- Step 2: Database Seeding ---")
    try:
        import argparse as ap2
        db_args = ap2.Namespace(
            output=args.output,
            admin_email=os.environ.get("BOOTSTRAP_ADMIN_EMAIL", None),
        )
        from setup.database import run_database_setup
        rc = await run_database_setup(db_args)
        if rc != 0:
            exit_code = rc
            print("  ⚠ Database seeding completed with errors")
        print()
    except Exception as exc:
        logger.exception("Database seeding failed")
        exit_code = 1
        print(f"  ✗ Database seeding error: {exc}")
        print()

    # Step 3: Certificates
    print("--- Step 3: Certificate Authority ---")
    try:
        import argparse as ap3
        cert_args = ap3.Namespace(output=args.output)
        from setup.certificates import run_certificates_setup
        rc = await run_certificates_setup(cert_args)
        if rc != 0:
            exit_code = rc
            print("  ⚠ Certificate setup completed with errors")
        print()
    except Exception as exc:
        logger.exception("Certificate setup failed")
        exit_code = 1
        print(f"  ✗ Certificate setup error: {exc}")
        print()

    print("=" * 80)
    if exit_code == 0:
        print("✓ SETUP COMPLETE")
    else:
        print("⚠ SETUP COMPLETED WITH ERRORS — check output above")
    print("=" * 80)
    print()
    print("You can now start the backend with:")
    print("  .\\parthenon.ps1 start -Services backend")
    print()
    print("Admin credentials (default):")
    print("  Username: admin")
    print("  Password: admin")
    print()

    return exit_code
