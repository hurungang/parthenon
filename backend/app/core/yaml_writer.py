"""Atomic YAML config writer — writes resolved OIDC settings to config/identity.yaml.

Never writes client_secret (secrets live encrypted in the DB only).
Uses write-to-temp-then-rename for crash safety.
"""

import logging
import os

import yaml

from app.core.yaml_config import IdentityYamlConfig, _get_yaml_path

logger = logging.getLogger(__name__)

# Keys that must never appear in the YAML file
_SECRET_KEYS: frozenset[str] = frozenset({"client_secret"})


def write_identity_yaml(config: IdentityYamlConfig) -> None:
    """Write *config* to ``config/identity.yaml`` atomically.

    The function:
    1. Filters out any secret keys (``client_secret`` etc.).
    2. Writes to a sibling ``.tmp`` file.
    3. Renames (atomic on POSIX; best-effort on Windows) to the target path.

    Args:
        config: Typed dict of non-sensitive identity settings to persist.
    """
    target_path = _get_yaml_path()
    tmp_path = target_path.with_suffix(".yaml.tmp")

    # Build serialisable dict, excluding secrets and empty values
    data: dict[str, object] = {
        k: v
        for k, v in config.model_dump().items()
        if k not in _SECRET_KEYS and v is not None and v != ""
    }

    # Ensure the parent directory exists
    target_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, default_flow_style=False, allow_unicode=True, sort_keys=True)

        # Atomic rename
        os.replace(tmp_path, target_path)
        logger.info("identity.yaml written to %s", target_path)
    except Exception:
        # Best-effort cleanup of the temp file
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
