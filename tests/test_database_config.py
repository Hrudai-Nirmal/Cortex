"""Database configuration tests protect packaged migration connectivity."""

from __future__ import annotations

from alembic.config import Config

from cortex.config import Settings
from cortex.database_config import applyAlembicDatabaseUrl


def buildSettings(**overrides: object) -> Settings:
    """Create deterministic settings for database-configuration tests."""
    values = {
        "environment": "test",
        "devMode": False,
        "requiredAccelerator": "cpu",
        "databaseUrl": "postgresql+asyncpg://cortex:cortex@postgres:5432/cortex",
        "ollamaBaseUrl": "http://ollama:11434",
        "objectStorageRoot": ".cortex-data/test-object-storage",
        "consoleHost": "console.example.test",
        "queryHost": "query.example.test",
        "consolePublicUrl": "https://console.example.test",
        "queryPublicUrl": "https://query.example.test",
    }
    values.update(overrides)
    return Settings(**values)


def testApplyAlembicDatabaseUrlOverridesIniDefaults() -> None:
    """Runtime database settings must override localhost ini defaults inside containers."""
    config = Config()
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://cortex:cortex@127.0.0.1:5432/cortex")

    applyAlembicDatabaseUrl(config, buildSettings())

    assert config.get_main_option("sqlalchemy.url") == (
        "postgresql+asyncpg://cortex:cortex@postgres:5432/cortex"
    )


def testSettingsReadSnakeCaseEnvironmentVariables(monkeypatch) -> None:
    """Packaged snake_case environment variables must hydrate camelCase settings fields."""
    monkeypatch.setenv("CORTEX_ENVIRONMENT", "production")
    monkeypatch.setenv("CORTEX_DEV_MODE", "false")
    monkeypatch.setenv("CORTEX_DATABASE_URL", "postgresql+asyncpg://cortex:cortex@postgres:5432/cortex")
    monkeypatch.setenv("CORTEX_OLLAMA_BASE_URL", "http://ollama:11434")
    monkeypatch.setenv("CORTEX_OBJECT_STORAGE_ROOT", "/var/lib/cortex/object-storage")
    monkeypatch.setenv("CORTEX_REQUIRED_ACCELERATOR", "cpu")
    monkeypatch.setenv("CORTEX_CONSOLE_HOST", "cortex-console.client.internal")
    monkeypatch.setenv("CORTEX_QUERY_HOST", "cortex-app.client.internal")
    monkeypatch.setenv("CORTEX_CONSOLE_PUBLIC_URL", "https://cortex-console.client.internal")
    monkeypatch.setenv("CORTEX_QUERY_PUBLIC_URL", "https://cortex-app.client.internal")

    settings = Settings()

    assert settings.databaseUrl == "postgresql+asyncpg://cortex:cortex@postgres:5432/cortex"
    assert settings.consoleHost == "cortex-console.client.internal"
    assert settings.queryHost == "cortex-app.client.internal"
