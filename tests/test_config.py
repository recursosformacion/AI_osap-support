"""Tests de configuración de OSAP Support (Fase 1)."""

from __future__ import annotations

from infrastructure.config import DatabaseConfig, IdentityConfig, Settings


def test_database_defaults_to_osap_support() -> None:
    db = DatabaseConfig()
    assert db.name == "osap_support"
    assert "osap_support" in db.dsn
    assert "osap_support" in db.sync_dsn


def test_settings_expose_database_and_identity() -> None:
    settings = Settings(env="test")
    assert settings.server.env == "test"
    assert settings.database.name == "osap_support"
    assert settings.identity.audience == "osap-support"


def test_identity_config_env_prefix() -> None:
    assert DatabaseConfig.model_config["env_prefix"] == "OSAP_SUPPORT_DB_"
    assert IdentityConfig.model_config["env_prefix"] == "OSAP_SUPPORT_AUTH_"
