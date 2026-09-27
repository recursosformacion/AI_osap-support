"""Tests de configuración de OSAP Support (Fase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.config import DatabaseConfig, IdentityConfig, Settings


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


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


def test_identity_service_audience_from_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`[identity] service_audience` debe aplicarse (bug de cableado 4.2).

    Distingue la audiencia de tokens de usuario (`audience`) de la de service tokens M2M
    (`service_audience`): la config de producción declara `aud=osap-support` para M2M.
    """
    monkeypatch.delenv("OSAP_SUPPORT_AUTH_SERVICE_AUDIENCE", raising=False)
    monkeypatch.delenv("OSAP_SUPPORT_AUTH_AUDIENCE", raising=False)
    toml = _write_toml(
        tmp_path / "osap.toml",
        "\n".join(
            [
                "[identity]",
                'audience = "osap-api"',
                'service_audience = "osap-support"',
            ]
        ),
    )
    settings = Settings(env="test", toml_file=toml)
    assert settings.identity.audience == "osap-api"
    assert settings.identity.service_audience == "osap-support"


def test_identity_service_audience_env_overrides_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OSAP_SUPPORT_AUTH_SERVICE_AUDIENCE", "otro-servicio")
    toml = _write_toml(
        tmp_path / "osap.toml", '[identity]\nservice_audience = "osap-support"\n'
    )
    settings = Settings(env="test", toml_file=toml)
    assert settings.identity.service_audience == "otro-servicio"
