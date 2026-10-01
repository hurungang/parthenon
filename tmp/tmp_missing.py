import os, sys
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")
sys.path.insert(0, "backend")

import app.db.models  # noqa
import importlib.util
spec = importlib.util.spec_from_file_location("sweep", "backend/tests/test_tenant_isolation_sweep.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
missing = [c.__name__ for c in mod.SCOPED_MODEL_CLASSES if c not in mod._OWN_KWARGS]
extra = [c.__name__ for c in mod._OWN_KWARGS if c not in mod.SCOPED_MODEL_CLASSES]
print("missing builders:", missing)
print("extra builders:", extra)
print("scoped count:", len(mod.SCOPED_MODEL_CLASSES))
print("registry count:", len(mod.TENANT_AGNOSTIC_REGISTRY))
