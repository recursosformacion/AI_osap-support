"""Configuración de OSAP Support.

Convención del ecosistema OSAP (como osap-api/osap-storage): un único fichero TOML por
entorno, gitignored, con las secciones del servicio:

- `osap.toml`            → desarrollo/sandbox (local)
- `osap.production.toml` → producción (se despliega como `osap.toml` en el host)

Precedencia: variable de entorno (`OSAP_SUPPORT_*`) > `osap.toml` (secciones) > defaults.
Se conserva `config.yaml` como capa opcional adicional (osap-auth) para valores no
secretos, pero el contrato canónico pasa a ser el TOML.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]
from pydantic_settings import BaseSettings, SettingsConfigDict

from domain.entities import ContributionType
from domain.recognitions_rules import RecognitionRules

PROJECT_ROOT = Path(__file__).resolve().parent.parent

class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OSAP_SUPPORT_DB_", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 3306
    name: str = "osap_support"
    user: str = "osap2027"
    # Vacía por defecto: el password de BD SIEMPRE viene de env/TOML (osap.toml
    # gitignored) o del entorno de despliegue. Nunca se versiona en el repo.
    password: str = ""

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

    # Vacías por defecto: en production el arranque exige JWKS/issuer reales de
    # osap-auth (ver api.main._identity_for); nunca se usan placeholders.
    jwks_uri: str = ""
    issuer: str = ""
    audience: str = "osap-support"
    service_audience: str = ""  # service tokens M2M (si vacío: same as audience)
    service_client_id: str = ""
    service_client_secret: str = ""
    jwks_cache_ttl_seconds: int = 300


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
    # Service token estático de dev/test para la frontera M2M (contrato de audiencia 4D).
    dev_service_token: str = "dev-service-token"


class PaymentConfig(BaseSettings):
    """Configuración del proveedor de pagos (PayPal, decisión 2026-09).

    Prefijo `OSAP_SUPPORT_PAYPAL_` (o sección `[paypal]` de osap.toml). El modo
    (`sandbox`|`live`) y las credenciales se validan en el wiring: en production sin
    credenciales reales el arranque FALLA.
    """

    model_config = SettingsConfigDict(env_prefix="OSAP_SUPPORT_PAYPAL_", extra="ignore")

    mode: str = ""  # sandbox | live (vacío = no configurado)
    # Opt-in de desarrollo: en entornos no productivos, usar PayPal REAL (sandbox)
    # en lugar del FakePaymentProvider. Por defecto False (fake en dev/test).
    dev_real: bool = False
    client_id: str = ""
    client_secret: str = ""
    webhook_id: str = ""
    # Plan IDs de PayPal por nivel×periodicidad (se crean en el panel/Sandbox; el
    # importe/plan lo fija PayPal, nunca el navegador). Niveles reales del dominio:
    # supporter/contributor/voice/founder × monthly/yearly.
    plan_supporter_monthly: str = ""
    plan_supporter_yearly: str = ""
    plan_contributor_monthly: str = ""
    plan_contributor_yearly: str = ""
    plan_voice_monthly: str = ""
    plan_voice_yearly: str = ""
    plan_founder_monthly: str = ""
    plan_founder_yearly: str = ""

    def plan_ids(self) -> dict[tuple[str, str], str]:
        return {
            ("supporter", "monthly"): self.plan_supporter_monthly,
            ("supporter", "yearly"): self.plan_supporter_yearly,
            ("contributor", "monthly"): self.plan_contributor_monthly,
            ("contributor", "yearly"): self.plan_contributor_yearly,
            ("voice", "monthly"): self.plan_voice_monthly,
            ("voice", "yearly"): self.plan_voice_yearly,
            ("founder", "monthly"): self.plan_founder_monthly,
            ("founder", "yearly"): self.plan_founder_yearly,
        }


class SmtpConfig(BaseSettings):
    """Configuración del proveedor de email SMTP (ADR-006, Fase 7).

    Prefijo `OSAP_SUPPORT_SMTP_`. El worker (no uvicorn) es quien envía.
    """

    model_config = SettingsConfigDict(env_prefix="OSAP_SUPPORT_SMTP_", extra="ignore")

    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = "support@openmusicrepository.com"
    tls: bool = True


class RecognitionConfig:
    """Reglas de reconocimientos (ADR-015/016/017, Fase 1 cerrada).

    Parámetros de ECOSISTEMA (ADR-016: no por proyecto). Env `OSAP_SUPPORT_RECOGNITIONS_*`
    > sección `[recognitions]` del toml > defaults. `contributor_types` acepta lista en
    toml o CSV en env (valores ContributionType: review, content, ...).
    """

    def __init__(self) -> None:
        self.supporter_window_days: int = 365
        self.contributor_threshold: int = 150
        self.contributor_types: list[str] = [
            "review",
            "content",
            "translation",
            "development",
            "documentation",
        ]
        self.founder_criterion_id: str = "founder-2026"


@dataclass(frozen=True)
class M2mClientConfig:
    """Allowlist M2M: un service client autenticado emite contribuciones como `source`
    SOLO para los proyectos listados (ADR-017). `source` se deriva de aquí; nunca del body."""

    client_id: str
    source: str
    projects: list[str] = field(default_factory=list)


class M2mConfig:
    """Allowlist de clientes M2M (`[m2m]`, sección toml)."""

    def __init__(self) -> None:
        self.clients: list[M2mClientConfig] = []

    def scope_for(self, client_id: str) -> M2mClientConfig | None:
        for client in self.clients:
            if client.client_id == client_id:
                return client
        return None


# Mapeo de secciones TOML → env vars OSAP_SUPPORT_* (precedencia: env > toml > defaults).
# `None` como convertidor = copia literal (str).
_TOML_TO_ENV: dict[str, list[tuple[str, str, Any]]] = {
    "db": [
        ("host", "OSAP_SUPPORT_DB_HOST", str),
        ("port", "OSAP_SUPPORT_DB_PORT", int),
        ("name", "OSAP_SUPPORT_DB_NAME", str),
        ("user", "OSAP_SUPPORT_DB_USER", str),
        ("password", "OSAP_SUPPORT_DB_PASSWORD", str),
    ],
    "identity": [
        ("jwks_uri", "OSAP_SUPPORT_AUTH_JWKS_URI", str),
        ("issuer", "OSAP_SUPPORT_AUTH_ISSUER", str),
        ("audience", "OSAP_SUPPORT_AUTH_AUDIENCE", str),
        ("service_client_id", "OSAP_SUPPORT_AUTH_SERVICE_CLIENT_ID", str),
        ("service_client_secret", "OSAP_SUPPORT_AUTH_SERVICE_CLIENT_SECRET", str),
        ("jwks_cache_ttl_seconds", "OSAP_SUPPORT_AUTH_JWKS_CACHE_TTL_SECONDS", int),
    ],
    "paypal": [
        ("mode", "OSAP_SUPPORT_PAYPAL_MODE", str),
        ("dev_real", "OSAP_SUPPORT_PAYPAL_DEV_REAL", bool),
        ("client_id", "OSAP_SUPPORT_PAYPAL_CLIENT_ID", str),
        ("client_secret", "OSAP_SUPPORT_PAYPAL_CLIENT_SECRET", str),
        ("webhook_id", "OSAP_SUPPORT_PAYPAL_WEBHOOK_ID", str),
        ("plan_supporter_monthly", "OSAP_SUPPORT_PAYPAL_PLAN_SUPPORTER_MONTHLY", str),
        ("plan_supporter_yearly", "OSAP_SUPPORT_PAYPAL_PLAN_SUPPORTER_YEARLY", str),
        ("plan_contributor_monthly", "OSAP_SUPPORT_PAYPAL_PLAN_CONTRIBUTOR_MONTHLY", str),
        ("plan_contributor_yearly", "OSAP_SUPPORT_PAYPAL_PLAN_CONTRIBUTOR_YEARLY", str),
        ("plan_voice_monthly", "OSAP_SUPPORT_PAYPAL_PLAN_VOICE_MONTHLY", str),
        ("plan_voice_yearly", "OSAP_SUPPORT_PAYPAL_PLAN_VOICE_YEARLY", str),
        ("plan_founder_monthly", "OSAP_SUPPORT_PAYPAL_PLAN_FOUNDER_MONTHLY", str),
        ("plan_founder_yearly", "OSAP_SUPPORT_PAYPAL_PLAN_FOUNDER_YEARLY", str),
    ],
    "smtp": [
        ("host", "OSAP_SUPPORT_SMTP_HOST", str),
        ("port", "OSAP_SUPPORT_SMTP_PORT", int),
        ("username", "OSAP_SUPPORT_SMTP_USERNAME", str),
        ("password", "OSAP_SUPPORT_SMTP_PASSWORD", str),
        ("from_address", "OSAP_SUPPORT_SMTP_FROM", str),
        ("tls", "OSAP_SUPPORT_SMTP_TLS", bool),
    ],
}


class Settings:
    """Configuración del servicio.

    Convención del ecosistema (igual que osap-api/osap-storage): la configuración vive
    en el fichero TOML activo del servicio — `osap.toml` en desarrollo; en producción se
    despliega `osap.production.toml` COMO `osap.toml` en el host. Los tests dependen del
    mismo mecanismo (mismo fichero que la app), NO de un segundo sistema de configuración.

    Precedencia: env (`OSAP_SUPPORT_*`) > osap.toml (secciones) > defaults.

    - `toml_file=None` (default) → carga `PROJECT_ROOT/osap.toml` si existe.
    - `toml_file=<Path>` → carga ese fichero (p. ej. un osap.production.toml de prueba).
    - `toml_file=Path("<no existe>")` o entorno sin toml → defaults + env (fail-fast en
      producción con mensaje claro si falta una sección obligatoria).
    """

    def __init__(
        self,
        *,
        env: str = "development",
        config_file: Path | None = None,
        toml_file: Path | None | bool = None,
    ) -> None:
        self.server = ServerConfig()
        self.server.env = env
        self._yaml_data: dict[str, Any] = {}
        self._toml_data: dict[str, Any] = {}

        if config_file is not None and config_file.exists():
            self._load_yaml(config_file)

        if toml_file is None:
            toml_file = PROJECT_ROOT / "osap.toml"
        if isinstance(toml_file, Path) and toml_file.exists():
            self._load_toml(toml_file)

        self.database = DatabaseConfig()
        self.identity = IdentityConfig()
        self.payment = PaymentConfig()
        self.smtp = SmtpConfig()
        self.recognitions = RecognitionConfig()
        self.m2m = M2mConfig()
        _apply_server_env(self.server)
        self._apply_toml_values()
        self._apply_recognitions()
        self._apply_m2m()
        self._apply_yaml(self._yaml_data)

    # -- TOML (convención ecosistema: osap.toml / osap.production.toml) ---------

    def _load_toml(self, path: Path) -> None:
        with path.open("rb") as handle:
            self._toml_data = tomllib.load(handle)

    def _apply_toml_values(self) -> None:
        """Aplica valores del TOML SOLO donde la env NO está definida (env > toml).

        No toca `os.environ`: cada Settings es independiente (hermético en tests).
        """
        sections = {
            "db": self.database,
            "identity": self.identity,
            "paypal": self.payment,
            "smtp": self.smtp,
        }
        for section, target in sections.items():
            block = self._toml_data.get(section)
            if not isinstance(block, dict):
                continue
            for key, env_var, conv in _TOML_TO_ENV.get(section, []):
                if os.environ.get(env_var) is not None:
                    continue
                value = block.get(key)
                if value is None:
                    continue
                setattr(target, key, _coerce_typed(key, value, conv))

    def _apply_recognitions(self) -> None:
        """Aplica `[recognitions]` y env `OSAP_SUPPORT_RECOGNITIONS_*` (env > toml)."""
        cfg = self.recognitions
        block = self._toml_data.get("recognitions")
        block = block if isinstance(block, dict) else {}

        if "supporter_window_days" in block and not os.environ.get(
            "OSAP_SUPPORT_RECOGNITIONS_SUPPORTER_WINDOW_DAYS"
        ):
            cfg.supporter_window_days = int(block["supporter_window_days"])
        if "contributor_threshold" in block and not os.environ.get(
            "OSAP_SUPPORT_RECOGNITIONS_CONTRIBUTOR_THRESHOLD"
        ):
            cfg.contributor_threshold = int(block["contributor_threshold"])
        if "founder_criterion_id" in block and not os.environ.get(
            "OSAP_SUPPORT_RECOGNITIONS_FOUNDER_CRITERION_ID"
        ):
            cfg.founder_criterion_id = str(block["founder_criterion_id"])
        if "contributor_types" in block and not os.environ.get(
            "OSAP_SUPPORT_RECOGNITIONS_CONTRIBUTOR_TYPES"
        ):
            raw_types = block["contributor_types"]
            if isinstance(raw_types, list):
                cfg.contributor_types = [str(t) for t in raw_types]

        value = os.environ.get("OSAP_SUPPORT_RECOGNITIONS_SUPPORTER_WINDOW_DAYS")
        if value is not None:
            cfg.supporter_window_days = int(value)
        value = os.environ.get("OSAP_SUPPORT_RECOGNITIONS_CONTRIBUTOR_THRESHOLD")
        if value is not None:
            cfg.contributor_threshold = int(value)
        value = os.environ.get("OSAP_SUPPORT_RECOGNITIONS_FOUNDER_CRITERION_ID")
        if value is not None:
            cfg.founder_criterion_id = value
        value = os.environ.get("OSAP_SUPPORT_RECOGNITIONS_CONTRIBUTOR_TYPES")
        if value is not None:
            cfg.contributor_types = [t.strip() for t in value.split(",") if t.strip()]

    def _apply_m2m(self) -> None:
        """Carga la allowlist `[m2m]` (solo toml; no hay secretos ni env de listas)."""
        block = self._toml_data.get("m2m")
        if not isinstance(block, dict):
            return
        raw_clients = block.get("clients")
        if not isinstance(raw_clients, list):
            return
        for item in raw_clients:
            if not isinstance(item, dict):
                continue
            client_id = item.get("client_id")
            source = item.get("source")
            if not client_id or not source:
                continue
            projects = item.get("projects")
            self.m2m.clients.append(
                M2mClientConfig(
                    client_id=str(client_id),
                    source=str(source),
                    projects=[str(p) for p in projects] if isinstance(projects, list) else [],
                )
            )

    @property
    def default_toml_path(self) -> Path:
        return PROJECT_ROOT / "osap.toml"

    # -- config.yaml (capa opcional osap-auth) ---------------------------------

    def _load_yaml(self, path: Path) -> None:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        self._yaml_data = data

    def _apply_yaml(self, data: dict[str, Any]) -> None:
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

        dbt = data.get("database", {})
        if not isinstance(dbt, dict):
            return
        # config.yaml es la capa de menor precedencia (env > toml > yaml > defaults).
        for dbfield in ("host", "port", "name", "user", "password"):
            if dbfield in dbt:
                env = os.environ.get(f"OSAP_SUPPORT_DB_{dbfield.upper()}")
                if env is not None:
                    continue
                toml = (self._toml_data.get("db") or {}).get(dbfield)
                if toml is not None:
                    continue
                setattr(self.database, dbfield, dbt[dbfield])

    def config_yaml(self) -> Path | None:
        path = PROJECT_ROOT / "config.yaml"
        return path if path.exists() else None


def _apply_server_env(server: ServerConfig) -> None:
    """Host/port/env/debug/cors vía env (precedencia máxima)."""
    value = os.environ.get("OSAP_SUPPORT_SERVER_HOST")
    if value:
        server.host = value
    value = os.environ.get("OSAP_SUPPORT_SERVER_PORT")
    if value:
        server.port = int(value)
    value = os.environ.get("OSAP_SUPPORT_SERVER_ENV")
    if value:
        server.env = value
    value = os.environ.get("OSAP_SUPPORT_SERVER_DEBUG")
    if value is not None and value.lower() in ("1", "true", "yes"):
        server.debug = True
    origins = os.environ.get("OSAP_SUPPORT_CORS_ORIGINS")
    if origins:
        server.cors_origins = [o.strip() for o in origins.split(",") if o.strip()]


def _coerce_typed(key: str, value: Any, conv: Any) -> Any:
    """Convierte el valor TOML al tipo del campo destino."""
    if conv is int:
        return int(value)
    if conv is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    return str(value)


@lru_cache
def load_settings() -> Settings:
    # Runtime (web/worker): osap.toml del servicio (dev) o desplegado como osap.toml en
    # producción. `config.yaml` (capa osap-auth) queda como capa menor, si existe.
    settings = Settings(env=os.environ.get("OSAP_SUPPORT_ENV", "development"))
    yaml_path = settings.config_yaml()
    if yaml_path is not None:
        settings = Settings(config_file=yaml_path)
    return settings


def recognition_rules_from_settings(settings: Settings) -> RecognitionRules:
    """Adapta `[recognitions]` (config) al value object de reglas del dominio.

    Valida que los tipos del bucket existan en `ContributionType` (fail-fast en wiring).
    """
    cfg = settings.recognitions
    types: set[ContributionType] = set()
    for raw in cfg.contributor_types:
        types.add(ContributionType(str(raw).strip().lower()))
    return RecognitionRules(
        supporter_window_days=cfg.supporter_window_days,
        contributor_threshold=cfg.contributor_threshold,
        contributor_types=frozenset(types),
        founder_criterion_id=cfg.founder_criterion_id,
    )


def m2m_scope_for_settings(settings: Settings, client_id: str) -> M2mClientConfig | None:
    """Devuelve la allowlist M2M del client autenticado, si existe."""
    return settings.m2m.scope_for(client_id)
