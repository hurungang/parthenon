import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa: F401 - import all
from app.db.session import Base

scoped, agnostic, join_tables = [], [], []
for mapper in Base.registry.mappers:
    cls = mapper.class_
    table = mapper.local_table
    if table is None or mapper.inherits:
        continue
    has_tenant = "tenant_id" in table.columns.keys()
    if has_tenant:
        scoped.append(cls.__name__)
    else:
        # check if it's an association table (no primary key of its own / class mapped to same table)
        agnostic.append((cls.__name__, table.name, len(table.columns)))

print("SCOPED MODELS (%d):" % len(scoped))
for n in sorted(scoped): print("  ", n)
print()
print("AGNOSTIC MODELS (%d):" % len(agnostic))
for n, t, c in sorted(agnostic): print("  ", n, "->", t, f"({c} cols)")

# Also enumerate pure Table objects (association tables) in metadata without a mapper
print()
print("TABLES WITHOUT MAPPED CLASS (association tables):")
mapped_tables = {m.local_table.name for m in Base.registry.mappers if m.local_table is not None}
for tname, table in sorted(Base.metadata.tables.items()):
    if tname not in mapped_tables:
        print("  ", tname, "tenant_id" in table.columns.keys(), f"({len(table.columns)} cols)")
