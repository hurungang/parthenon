# Backend — FastAPI Application

The Parthenon backend is a Python 3.11+ FastAPI application with async SQLAlchemy 2, PostgreSQL 16, and Redis.

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
