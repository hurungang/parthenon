import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from app.db.session import Base

for mapper in sorted(Base.registry.mappers, key=lambda m: m.class_.__name__):
    cls = mapper.class_
    table = mapper.local_table
    if table is None or mapper.inherits:
        continue
    if "tenant_id" not in table.columns.keys():
        continue
    required = []
    for c in table.columns:
        if c.primary_key or c.nullable:
            continue
        if c.default is not None or c.server_default is not None:
            continue
        fk = " FK->" + ",".join(f"{fk.column.table.name}.{fk.column.name}" for fk in c.foreign_keys) if c.foreign_keys else ""
        required.append(f"{c.name}:{c.type}{fk}")
    print(f"{cls.__name__} [{table.name}]\n    req: {required}")
