# Backend — FastAPI Application

The Parthenon backend is a Python 3.11+ FastAPI application with async SQLAlchemy 2, PostgreSQL 16, and Redis.

Contributors working in this package must follow the repository CLA flow before
their pull requests can be merged. See [../CLA.md](../CLA.md) and
[../CONTRIBUTING.md](../CONTRIBUTING.md).

## Structure

```
backend/
├── app/
│   ├── api/            # Route handlers
│   ├── core/           # Config, OIDC client, credential vault
│   ├── db/             # Models and session factory
│   ├── middleware/     # JWT auth middleware
│   ├── schemas/        # Pydantic v2 request/response models
│   └── services/       # Business logic services
├── tests/              # Unit and integration tests
└── alembic/            # Database migrations
```
