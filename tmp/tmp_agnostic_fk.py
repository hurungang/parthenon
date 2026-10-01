import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from app.db.session import Base

scoped_tables = set()
for m in Base.registry.mappers:
    if m.local_table is not None and not m.inherits and "tenant_id" in m.local_table.columns.keys():
        scoped_tables.add(m.local_table.name)

for mapper in sorted(Base.registry.mappers, key=lambda m: m.class_.__name__):
    cls, table = mapper.class_, mapper.local_table
    if table is None or mapper.inherits or "tenant_id" in table.columns.keys():
        continue
    fks = []
    for c in table.columns:
        for fk in c.foreign_keys:
            tgt = fk.column.table.name
            fks.append(f"{c.name}->{tgt}{'(SCOPED)' if tgt in scoped_tables else ''}")
    print(f"{cls.__name__} [{table.name}]: fks={fks}")
