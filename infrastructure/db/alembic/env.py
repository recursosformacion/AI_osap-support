"""Configuración de Alembic para osap-support.

ADR-003: BD propia `osap_support` (acceso solo vía la propia capa de infraestructura).
El DSN se obtiene de `infrastructure/config.py` (por entorno). No se crean tablas de
negocio en esta fase; estas migraciones serán el punto de partida para fases futuras.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from infrastructure.config import load_settings
from infrastructure.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    """URL de BD: la de alembic.ini si está definida (tests), si no la de la config
    del servicio (producción: `osap_support` en MariaDB, ADR-003)."""
    from alembic import context as _ctx

    ini_url = _ctx.config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    settings = load_settings()
    return settings.database.sync_dsn


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()  # type: ignore[attr-defined]


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
