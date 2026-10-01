import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from sqlalchemy import Enum as SAEnum
from app.db.session import Base

mismatch = []
for mapper in Base.registry.mappers:
    cls, table = mapper.class_, mapper.local_table
    if table is None or mapper.inherits:
        continue
    for c in table.columns:
        if isinstance(c.type, SAEnum) and c.type.enum_class is not None:
            for member in c.type.enum_class:
                if member.name != member.value:
                    mismatch.append(f"{cls.__name__}.{c.name}: {member.name}={member.value!r}")
print("MISMATCHES (name != value):")
print("\n".join(mismatch) if mismatch else "  none — all enum member names equal values")
