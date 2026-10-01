import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from sqlalchemy import Enum as SAEnum
from app.db.session import Base

for mapper in sorted(Base.registry.mappers, key=lambda m: m.class_.__name__):
    cls = mapper.class_
    table = mapper.local_table
    if table is None or mapper.inherits or "tenant_id" not in table.columns.keys():
        continue
    enums = []
    for c in table.columns:
        if isinstance(c.type, SAEnum):
            enums.append(f"{c.name}={list(c.type.enums)[:6]}")
    uniques = [
        f"{[col.name for col in u.columns]}"
        for u in table.constraints if u.__class__.__name__ == "UniqueConstraint"
    ]
    if enums or uniques:
        print(f"{cls.__name__}: enums={enums} uniques={uniques}")
