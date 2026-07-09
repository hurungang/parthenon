"""Parthenon Setup Tool — environment bootstrapping CLI.

This module is separate from the runtime application (``backend/app/``).
It handles identity provider provisioning, database seeding, certificate
authority bootstrapping, and development environment initialization.

All operations are idempotent — running them on an already-initialized
environment detects existing state and reports it without errors.

Usage:
    python -m setup.main <sub-command> [options]
    python -m setup.main dev       # Full local-dev bootstrap
    python -m setup.main identity   # Provision Keycloak realm and clients
    python -m setup.main database   # Seed roles, permissions, skills
    python -m setup.main certificates  # Bootstrap certificate authority
"""
