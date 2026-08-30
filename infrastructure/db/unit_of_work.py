"""Implementación SQLAlchemy de UnitOfWork (Fase 6).

Confirma/revierte una transacción sobre la sesión compartida por los repositorios.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from domain.ports.unit_of_work import UnitOfWork


class SqlAlchemyUnitOfWork(UnitOfWork):
    def __init__(self, session: Session) -> None:
        self._session = session

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
