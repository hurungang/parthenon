"""YAML config loader — reads config/identity.yaml into a typed Pydantic model.

Silent when the file is absent; raises ConfigurationError for invalid YAML.
Pydantic handles all type coercion and validation automatically.
"""

import logging
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

logger = logging.getLogger(__name__)

# Default path relative to repository root:
# backend/app/core/yaml_config.py → ../../../../config/identity.yaml
_DEFAULT_YAML_PATH = Path(__file__).parent.parent.parent.parent / "config" / "identity.yaml"


class IdentityYamlConfig(BaseModel):
    """Typed representation of config/identity.yaml.

    Extra keys are silently ignored; all fields are optional with safe defaults.
    Pydantic validates types and coerces scalars automatically.
    """

    model_config = ConfigDict(extra="ignore")

    provider_type: str = ""  # keycloak_bundled | keycloak_external | azure_entraid | unconfigured
    oidc_provider_url: str = ""
    realm_name: str = ""
    client_id: str = ""
    audience: str = ""
    jwt_algorithm: str = ""
    setup_complete: bool = False
    completed_at: str = ""  # ISO-8601


class ConfigurationError(Exception):
    """Raised when identity.yaml is present but structurally invalid."""


def _get_yaml_path() -> Path:
    """Return the resolved YAML path, preferring the IDENTITY_YAML_PATH env var."""
    env_override = os.environ.get("IDENTITY_YAML_PATH")
    if env_override:
        return Path(env_override)
    return _DEFAULT_YAML_PATH


def load_identity_yaml() -> IdentityYamlConfig:
    """Load and validate config/identity.yaml.

    Returns a default :class:`IdentityYamlConfig` when the file does not exist.
    Raises :class:`ConfigurationError` when the file exists but is not a valid
    YAML mapping or fails Pydantic validation.
    """
    path = _get_yaml_path()

    if not path.exists():
        logger.debug("identity.yaml not found at %s — using defaults", path)
        return IdentityYamlConfig()

    try:
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"identity.yaml is not valid YAML: {exc}") from exc

    # Empty file or comment-only file parses as None
    if raw is None:
        return IdentityYamlConfig()

    if not isinstance(raw, dict):
        raise ConfigurationError(f"identity.yaml must be a YAML mapping (got {type(raw).__name__})")

    try:
        config = IdentityYamlConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"identity.yaml has invalid values: {exc}") from exc

    logger.debug("Loaded identity.yaml from %s: %s", path, config.model_fields_set)
    return config
