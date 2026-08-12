"""Pytest configuration for mcp-demo-app tests.

Sets required environment variables before any app modules are imported
so that AppSettings() can initialise successfully.
"""
import os

# Must be set before any app.* imports trigger AppSettings()
os.environ.setdefault("KEYCLOAK_URL", "http://keycloak:8082")
os.environ.setdefault("KEYCLOAK_REALM", "ai_agents")
os.environ.setdefault("KEYCLOAK_CLIENT_ID", "mcp-demo-app-test")
os.environ.setdefault("KEYCLOAK_CLIENT_SECRET", "test-secret")
os.environ.setdefault("HUB_BASE_URL", "http://localhost:8000")
os.environ.setdefault("HUB_API_TOKEN", "test-token")
os.environ.setdefault("APP_BASE_URL", "http://localhost:7001")
