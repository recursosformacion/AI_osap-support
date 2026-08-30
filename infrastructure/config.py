"""Configuración de OSAP Support.

Sigue la convención de osap-auth: pydantic-settings para secretos/ajustes por variables
de entorno (prefijo `OSAP_SUPPORT_`) y, opcionalmente, un fichero `config.yaml` para
valores no secretos. ADR-003: BD propia `osap_support`, nunca de otros servicios.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSAP_SUPPORT_DB_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 3306
    name: str = "osap_support"
    user: str = "osap2027"
    password: str = "2027osapdb"

    @property
    def dsn(self) -> str:
        return f"mysql+aiomysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_dsn(self) -> str:
        """DSN síncrono para Alembic (usa PyMySQL)."""
        return f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


class IdentityConfig(BaseSettings):
    """Configuración de integración con Auth (ADR-002).

    Support valida los JWT de Auth para derivar `sub`; nunca crea usuarios locales.
    """

    model_config = SettingsConfigDict(env_prefix="OSAP_SUPPORT_AUTH_", extra="ignore")

    jwks_uri: str = "https://auth.osap/auth/.well-known/jwks.json"
    issuer: str = "https://auth.osap"
    audience: str = "osap-support"
    service_client_id: str = ""
    service_client_secret: str = ""


class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8300
    app_title: str = "OSAP Support"
    app_version: str = "0.1.0"
    env: str = "development"
    debug: bool = False
    cors_origins: list[str] = []
    # Identidad estática SOLO para dev/test (JWKS productivo queda ABIERTO, ADR-002).
    dev_token: str = "dev-token"
    dev_user_id: str = "dev-user"


class Settings:
    """Configuración global del servicio (estilo osap-auth)."""

    def __init__(self, *, env: str = "development", config_file: Path | None = None) -> None:
        self.server = ServerConfig()
        self.server.env = env
        self._yaml_data: dict[str, Any] = {}

        if config_file is not None and config_file.exists():
            self._load_yaml(config_file)

        self.database = DatabaseConfig()
        self.identity = IdentityConfig()
        self._apply_yaml(self._yaml_data)

    def _load_yaml(self, path: Path) -> None:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        app = data.get("app", {})
        server = data.get("server", {})
        env = app.get("env")
        if isinstance(env, str):
            self.server.env = env
        debug = app.get("debug")
        if debug is not None:
            self.server.debug = bool(debug)
        host = server.get("host")
        if isinstance(host, str):
            self.server.host = host
        port = server.get("port")
        if port is not None:
            self.server.port = int(port)
        origins = data.get("cors_origins", [])
        if isinstance(origins, str):
            origins = [o.strip() for o in origins.split(",") if o.strip()]
        self.server.cors_origins = list(origins)
        self._yaml_data = data

        dbt = data.get("database", {})
        if isinstance(dbt, dict):
            for field in ("host", "port", "name", "user", "password"):
                if field in dbt:
                    os.environ.setdefault(f"OSAP_SUPPORT_DB_{field.upper()}", str(dbt[field]))

    def _apply_yaml(self, data: dict[str, Any]) -> None:
        dbt = data.get("database", {})
        if not isinstance(dbt, dict):
            return
        for field in ("host", "port", "name", "user", "password"):
            if field in dbt and not os.environ.get(f"OSAP_SUPPORT_DB_{field.upper()}"):
                setattr(self.database, field, dbt[field])

    def config_yaml(self) -> Path | None:
        path = PROJECT_ROOT / "config.yaml"
        return path if path.exists() else None


@lru_cache
def load_settings() -> Settings:
    settings = Settings(env=os.environ.get("OSAP_SUPPORT_ENV", "development"))
    yaml_path = settings.config_yaml()
    if yaml_path is not None:
        settings = Settings(config_file=yaml_path)
    return settings
