"""Sesiones y conexión de BD para osap-support (Fase 3).

Solo infraestructura. El dominio no depende de esto (separación hexagonal).
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from infrastructure.config import load_settings


def make_engine(url: str | None = None) -> Engine:
    """Crea un engine (por defecto el DSN de osap_support desde config)."""
    if url is None:
        url = load_settings().database.sync_dsn
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    engine = engine or make_engine()
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
