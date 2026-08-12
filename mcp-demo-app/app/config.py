from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Keycloak — agent realm
    KEYCLOAK_URL: str
    KEYCLOAK_REALM: str = "ai_agents"
    KEYCLOAK_CLIENT_ID: str
    KEYCLOAK_CLIENT_SECRET: str

    # Keycloak — user realm (optional; falls back to agent realm when unset)
    KEYCLOAK_USER_REALM: str = ""
    KEYCLOAK_USER_CLIENT_ID: str = ""

    # Parthenon MCP Hub
    HUB_BASE_URL: str
    HUB_API_TOKEN: str

    # This app
    APP_BASE_URL: str
    APP_PORT: int = 7001
    APP_SLUG: str = "demo"


settings = AppSettings()
