"""Persistence helpers for workflow generation model selection."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

from app.core.config import get_settings
from app.core.yaml_config import _get_yaml_path


def get_workflow_generation_model_id() -> str | None:
    """Return the configured workflow generation model ID, or None if missing."""
    model_id = (get_settings().workflow_generation_model_id or "").strip()
    return model_id or None


def set_workflow_generation_model_id(model_id: str | None) -> None:
    """Persist workflow generation model ID into config/identity.yaml.

    The value is saved in the shared runtime config so all services and users
    resolve the same model selection.
    """
    target_path = _get_yaml_path()
    tmp_path = _tmp_yaml_path(target_path)

    existing: dict[str, object] = {}
    if target_path.exists():
        with open(target_path, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh)
        if isinstance(loaded, dict):
            existing = dict(loaded)

    if model_id and model_id.strip():
        existing["workflow_generation_model_id"] = model_id.strip()
    else:
        existing.pop("workflow_generation_model_id", None)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(tmp_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(existing, fh, default_flow_style=False, allow_unicode=False, sort_keys=True)
    os.replace(tmp_path, target_path)

    # The settings object is cached; refresh it after mutating identity.yaml.
    get_settings.cache_clear()


def _tmp_yaml_path(target_path: Path) -> Path:
    return target_path.with_suffix(".yaml.tmp")
