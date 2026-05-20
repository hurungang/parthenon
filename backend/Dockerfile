FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first for layer caching
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir -e ".[dev]"

# Copy application code
COPY . .

# Per-service entry point — override at build time or via docker compose `command:`
# control-center  → APP_MODULE=app.main:app            APP_PORT=8000
# agent-runtime   → APP_MODULE=app.agent_runtime.main:app   APP_PORT=8001
# communication-hub → APP_MODULE=app.communication_hub.main:app APP_PORT=8002
ARG APP_MODULE=app.main:app
ARG APP_PORT=8000

ENV APP_MODULE=${APP_MODULE}
ENV APP_PORT=${APP_PORT}

EXPOSE ${APP_PORT}

CMD ["sh", "-c", "uvicorn ${APP_MODULE} --host 0.0.0.0 --port ${APP_PORT} --reload"]
