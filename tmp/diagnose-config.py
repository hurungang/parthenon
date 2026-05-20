#!/usr/bin/env python3
"""Detailed diagnostic of backend configuration loading."""
import sys
import os
sys.path.insert(0, 'backend')

from pathlib import Path
from app.core.config import get_settings, _identity_yaml_path
from app.core.yaml_config import load_identity_yaml
import yaml

print("=" * 80)
print("CONFIGURATION DIAGNOSTIC")
print("=" * 80)
print()

# Check identity.yaml file location
yaml_path = _identity_yaml_path()
print(f"Identity YAML path: {yaml_path}")
print(f"File exists: {Path(yaml_path).exists()}")
print()

# Load raw YAML content
if Path(yaml_path).exists():
    print("Raw YAML content:")
    with open(yaml_path) as f:
        raw_yaml = yaml.safe_load(f)
        for key, value in raw_yaml.items():
            print(f"  {key}: {value}")
    print()

# Load via yaml_config helper
yaml_config = load_identity_yaml()
print("Loaded via load_identity_yaml():")
print(f"  audience: {yaml_config.audience}")
print(f"  client_id: {yaml_config.client_id}")
print(f"  realm_name: {yaml_config.realm_name}")
print(f"  agent_realm_name: {yaml_config.agent_realm_name}")
print()

# Load via Settings (which merges env + yaml)
settings = get_settings()
print("Loaded via get_settings():")
print(f"  jwt_audience: {settings.jwt_audience}")
print(f"  oidc_provider_url: {settings.oidc_provider_url}")
print()

# Check environment variables
print("Environment variables:")
env_vars = ['JWT_AUDIENCE', 'AUDIENCE', 'OIDC_PROVIDER_URL']
for var in env_vars:
    val = os.environ.get(var)
    if val:
        print(f"  {var}={val}")
if not any(os.environ.get(v) for v in env_vars):
    print("  (no relevant env vars set)")
print()

# Check what _agent_realm_client_id returns
from app.services.agents.identity_service import _agent_realm_client_id
print(f"_agent_realm_client_id() returns: {_agent_realm_client_id()}")
print()
