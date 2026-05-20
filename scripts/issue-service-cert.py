"""Issue a service certificate for the Communication Hub (or any internal service).

This script connects to the running backend to initialize the CA, then issues a
service certificate and writes the PEM files to disk.  The operator then sets:

    COMMUNICATION_HUB_CERT_PATH=/path/to/communication-hub.crt.pem
    COMMUNICATION_HUB_KEY_PATH=/path/to/communication-hub.key.pem

in the Communication Hub's environment so it can authenticate to /internal/* endpoints.

Usage (from repo root, with .venv activated):

    python scripts/issue-service-cert.py \
        --service-name communication-hub \
        --cert-out infra/certs/communication-hub.crt.pem \
        --key-out  infra/certs/communication-hub.key.pem

The script must be run with the same DATABASE_URL and CREDENTIAL_VAULT_KEY as the backend.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Ensure backend app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

os.environ.setdefault("ENVIRONMENT", "production")


async def main(service_name: str, cert_out: Path, key_out: Path) -> None:
    # Lazy imports so env vars are set first
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.db.session import Base
    from app.services.certificate_authority import (
        CertificateAuthorityService,
        initialize_ca,
    )

    settings = get_settings()
    engine = create_async_engine(settings.database_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with SessionLocal() as db:
        print(f"Initialising CA …")
        await initialize_ca(db)

        print(f"Issuing service certificate for '{service_name}' …")
        ca = CertificateAuthorityService()
        issued = await ca.issue_service(service_name)

    await engine.dispose()

    cert_out.parent.mkdir(parents=True, exist_ok=True)
    key_out.parent.mkdir(parents=True, exist_ok=True)

    cert_out.write_text(issued.certificate_pem)
    key_out.write_text(issued.private_key_pem)

    # Restrict private-key file permissions (owner-read-only) on POSIX systems
    if os.name == "posix":
        os.chmod(key_out, 0o600)

    print(f"Certificate written to : {cert_out}")
    print(f"Private key written to : {key_out}")
    print(f"Serial number          : {issued.serial_number}")
    print(f"Expires at             : {issued.expires_at.isoformat()}")
    print()
    print("Set the following environment variables on the Communication Hub:")
    print(f"  COMMUNICATION_HUB_CERT_PATH={cert_out.resolve()}")
    print(f"  COMMUNICATION_HUB_KEY_PATH={key_out.resolve()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Issue a Parthenon service certificate")
    parser.add_argument(
        "--service-name",
        default="communication-hub",
        help="Logical service name (encoded in certificate CN). Default: communication-hub",
    )
    parser.add_argument(
        "--cert-out",
        default="infra/certs/communication-hub.crt.pem",
        help="Output path for the certificate PEM file",
    )
    parser.add_argument(
        "--key-out",
        default="infra/certs/communication-hub.key.pem",
        help="Output path for the private key PEM file",
    )
    args = parser.parse_args()

    asyncio.run(main(args.service_name, Path(args.cert_out), Path(args.key_out)))
