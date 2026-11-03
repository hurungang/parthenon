"""CWD-independent certificate path resolution (FIX-20261031-131030).

Relative certificate paths (e.g. ``certs/communication-hub-cert.pem`` from
``.env`` defaults) historically resolved against the *process working
directory*.  A service restarted from the wrong working directory then
silently pointed at a non-existent path — the failure only surfaced lazily
at first use (``FileNotFoundError`` at LLM-call time) while health probes
stayed green.

Every service certificate path now resolves through :func:`resolve_cert_path`:

- absolute paths (and explicit ``*_CERT_PATH``-style env configuration that
  is absolute) pass through untouched — operators can always override;
- relative paths anchor to :data:`BACKEND_ROOT` (the ``backend/`` repo root),
  independent of the process CWD.

:func:`ensure_cert_files_exist` is used at startup so a misconfigured path
fails fast with a clear, actionable message instead of breaking lazily.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

#: The ``backend/`` repository root (this file lives at ``backend/app/core/``).
BACKEND_ROOT = Path(__file__).resolve().parents[2]


class CertValidationError(RuntimeError):
    """Raised at startup when a configured certificate file cannot be found."""


def resolve_cert_path(value: str | Path | None) -> Path | None:
    """Resolve a certificate path CWD-independently.

    Absolute paths are returned unchanged (explicit configuration wins);
    relative paths are anchored to :data:`BACKEND_ROOT`.
    """
    if value is None:
        return None
    path = Path(str(value)).expanduser()
    if path.is_absolute():
        return path
    return BACKEND_ROOT / path


def ensure_cert_files_exist(paths: Iterable[str | Path | None]) -> list[Path]:
    """Fail fast at startup: every resolved path must exist as a file.

    Returns the resolved paths on success; raises :class:`CertValidationError`
    listing every missing file otherwise.
    """
    resolved = [resolve_cert_path(p) for p in paths]
    missing = [str(p) for p in resolved if p is not None and not p.is_file()]
    if missing:
        raise CertValidationError(
            "Certificate file(s) not found: "
            + ", ".join(missing)
            + ". Set the *_CERT_PATH / *_KEY_PATH / CA_CERT_PATH environment "
            "variables to absolute paths, or bootstrap the certificates from "
            "Control Center before starting the service."
        )
    return [p for p in resolved if p is not None]
