"""Integration tests — Database isolation for Agent Runtime and Communication Hub (Task 7.5).

Verifies at import/module level that:
  - Agent Runtime module tree (app.agent_runtime.*) does not import database session factories
  - Communication Hub module tree (app.communication_hub.*) does not import database session factories
  - AR/CH use only their data clients (HTTP) for data access
  - No AsyncSession or get_db in AR/CH module source files

These are static analysis tests — they inspect source files and module imports
without running a live service.
"""
from __future__ import annotations

import ast
import importlib.util
import os
from pathlib import Path

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_source_root() -> Path:
    """Return the backend/app directory."""
    here = Path(__file__).parent
    # tests/integration/ → tests/ → backend/
    return here.parent.parent / "app"


def _collect_python_files(directory: Path) -> list[Path]:
    """Recursively collect all .py files under a directory."""
    return sorted(directory.rglob("*.py"))


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


DB_SESSION_PATTERNS = [
    "from app.db.session import",
    "from app.db import session",
    "AsyncSession",
    "get_db",
    "DbSession",
    "create_async_engine",
    "sessionmaker",
    "async_sessionmaker",
]

# These patterns are allowed in data_client.py / tests — but should NOT appear
# in the AR/CH core module files
DB_IMPORT_PATTERNS = [
    "app.db.session",
    "app.db.models",
    "AsyncSession",
    "get_db",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runtime database isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestAgentRuntimeDatabaseIsolation:
    """Agent Runtime must have zero direct database access."""

    def _get_ar_files(self) -> list[Path]:
        app_root = _get_source_root()
        ar_dir = app_root / "agent_runtime"
        return _collect_python_files(ar_dir) if ar_dir.exists() else []

    def test_agent_runtime_directory_exists(self):
        """Agent Runtime module directory exists."""
        app_root = _get_source_root()
        ar_dir = app_root / "agent_runtime"
        assert ar_dir.exists(), f"app/agent_runtime/ directory not found at {ar_dir}"

    def test_agent_runtime_has_no_database_url_dependency(self):
        """AR source files do not reference DATABASE_URL environment variable."""
        violations = []
        for path in self._get_ar_files():
            if path.name == "conftest.py" or "test_" in path.name:
                continue
            source = _read_source(path)
            if "DATABASE_URL" in source:
                violations.append(str(path))

        assert not violations, (
            f"Agent Runtime files reference DATABASE_URL (DB isolation violated):\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_agent_runtime_has_no_direct_db_session_imports(self):
        """AR source files do not import AsyncSession or get_db directly from app.db.session."""
        violations = []
        for path in self._get_ar_files():
            source = _read_source(path)
            # data_client.py is the only allowed place to reference httpx (not DB)
            if path.name in ("data_client.py", "__init__.py"):
                continue
            for pattern in ["from app.db.session import", "from app.db import session"]:
                if pattern in source:
                    violations.append(f"{path}: {pattern}")

        assert not violations, (
            "Agent Runtime directly imports DB session factory (must use data_client):\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_agent_runtime_data_client_exists(self):
        """AR has a data_client.py that abstracts all CC API calls."""
        app_root = _get_source_root()
        data_client = app_root / "agent_runtime" / "data_client.py"
        assert data_client.exists(), "agent_runtime/data_client.py does not exist"

    def test_agent_runtime_data_client_has_no_db_imports(self):
        """data_client.py itself must not import DB session — it uses httpx only."""
        app_root = _get_source_root()
        data_client = app_root / "agent_runtime" / "data_client.py"
        if not data_client.exists():
            pytest.skip("data_client.py not found")

        source = _read_source(data_client)
        forbidden = ["from app.db", "AsyncSession", "get_db", "sessionmaker"]
        for pattern in forbidden:
            assert pattern not in source, (
                f"agent_runtime/data_client.py imports DB directly ({pattern!r}); "
                "must use httpx only"
            )

    def test_agent_runtime_main_does_not_import_db_session(self):
        """AR main.py must not import database session factory."""
        app_root = _get_source_root()
        main_py = app_root / "agent_runtime" / "main.py"
        if not main_py.exists():
            pytest.skip("agent_runtime/main.py not found")

        source = _read_source(main_py)
        assert "from app.db.session import" not in source
        assert "get_db" not in source


# ═══════════════════════════════════════════════════════════════════════════════
# Communication Hub database isolation
# ═══════════════════════════════════════════════════════════════════════════════


class TestCommunicationHubDatabaseIsolation:
    """Communication Hub must have zero direct database access."""

    def _get_ch_files(self) -> list[Path]:
        app_root = _get_source_root()
        ch_dir = app_root / "communication_hub"
        return _collect_python_files(ch_dir) if ch_dir.exists() else []

    def test_communication_hub_directory_exists(self):
        """Communication Hub module directory exists."""
        app_root = _get_source_root()
        ch_dir = app_root / "communication_hub"
        assert ch_dir.exists(), f"app/communication_hub/ directory not found at {ch_dir}"

    def test_communication_hub_has_no_database_url_dependency(self):
        """CH source files do not reference DATABASE_URL."""
        violations = []
        for path in self._get_ch_files():
            if path.name == "conftest.py" or "test_" in path.name:
                continue
            source = _read_source(path)
            if "DATABASE_URL" in source:
                violations.append(str(path))

        assert not violations, (
            "Communication Hub files reference DATABASE_URL (DB isolation violated):\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_communication_hub_has_no_direct_db_session_imports(self):
        """CH source files do not import from app.db.session."""
        violations = []
        for path in self._get_ch_files():
            source = _read_source(path)
            if path.name in ("data_client.py", "__init__.py"):
                continue
            for pattern in ["from app.db.session import", "from app.db import session"]:
                if pattern in source:
                    violations.append(f"{path}: {pattern}")

        assert not violations, (
            "Communication Hub directly imports DB session factory:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_communication_hub_data_client_exists(self):
        """CH has a data_client.py."""
        app_root = _get_source_root()
        data_client = app_root / "communication_hub" / "data_client.py"
        assert data_client.exists(), "communication_hub/data_client.py does not exist"

    def test_communication_hub_data_client_has_no_db_imports(self):
        """CH data_client.py must use httpx only — no DB imports."""
        app_root = _get_source_root()
        data_client = app_root / "communication_hub" / "data_client.py"
        if not data_client.exists():
            pytest.skip("data_client.py not found")

        source = _read_source(data_client)
        forbidden = ["from app.db", "AsyncSession", "get_db", "sessionmaker"]
        for pattern in forbidden:
            assert pattern not in source, (
                f"communication_hub/data_client.py imports DB directly ({pattern!r})"
            )

    def test_communication_hub_main_does_not_import_db_session(self):
        """CH main.py must not import database session factory."""
        app_root = _get_source_root()
        main_py = app_root / "communication_hub" / "main.py"
        if not main_py.exists():
            pytest.skip("communication_hub/main.py not found")

        source = _read_source(main_py)
        assert "from app.db.session import" not in source
        assert "get_db" not in source


# ═══════════════════════════════════════════════════════════════════════════════
# Verify services expose data_client.py (not DB calls)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDataClientExists:
    """Both services must expose a data_client.py as the sole data access abstraction."""

    def test_ar_data_client_is_importable(self):
        """app.agent_runtime.data_client is importable without DB session."""
        # If importing raises because of missing DB → isolation broken
        try:
            from app.agent_runtime.data_client import ControlCenterDataClient
            assert ControlCenterDataClient is not None
        except ImportError as exc:
            pytest.fail(f"Cannot import agent_runtime.data_client: {exc}")

    def test_ch_data_client_is_importable(self):
        """app.communication_hub.data_client is importable without DB session."""
        try:
            from app.communication_hub.data_client import ControlCenterDataClient
            assert ControlCenterDataClient is not None
        except ImportError as exc:
            pytest.fail(f"Cannot import communication_hub.data_client: {exc}")
