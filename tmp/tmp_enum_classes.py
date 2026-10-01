import os
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://parthenon:parthenon@localhost:5432/parthenon_test")
os.environ.setdefault("CREDENTIAL_VAULT_KEY", "test-32-byte-key-for-aes-256-enc!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ENVIRONMENT", "test")

import app.db.models  # noqa
from sqlalchemy import Enum as SAEnum
from app.db.session import Base

wanted = {
    "AccessRequest": "status", "ModelConfig": "provider_type",
    "NotificationChannel": "channel_type", "Identity": "identity_type",
    "ScheduledJob": "target_type", "GuardrailThresholdEvent": None,
    "ModelGuardrailEvaluation": None, "ModelUsagePosture": None,
    "TenantQuotaUsage": "quota_type", "InterveneRequest": None,
    "TerminationRequest": None, "RuntimeToolCall": None,
    "NotificationLog": None, "TagDefinition": "scope",
    "AgentIdentity": "identity_type", "AgentDataType": None,
}
for mapper in Base.registry.mappers:
    cls, table = mapper.class_, mapper.local_table
    if table is None or mapper.inherits or cls.__name__ not in wanted:
        continue
    for c in table.columns:
        if isinstance(c.type, SAEnum) and c.type.enum_class is not None:
            if wanted[cls.__name__] is None or c.name == wanted[cls.__name__]:
                print(f"{cls.__name__}.{c.name} -> {c.type.enum_class.__module__}.{c.type.enum_class.__name__} members={[m.name for m in c.type.enum_class]}")
