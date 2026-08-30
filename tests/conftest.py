"""Fixtures de tests de osap-support (Fase 3).

Estrategia de BD aislada para tests: SQLite en memoria (sin servicios externos).
Se crean las tablas desde los modelos (infrastructure.db.models.Base.metadata).
Ninguna BD externa es modificada (ADR-003).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from infrastructure.db.models import Base


@pytest.fixture
def db_session() -> Iterator[Session]:
    # SQLite en memoria compartida entre threads (TestClient usa un hilo distinto):
    # StaticPool mantiene UNA conexión compartida y check_same_thread=False lo permite.
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()
