"""Port UnitOfWork de OSAP Support (Fase 6).

Permite que el procesamiento del webhook (registro de PaymentEvent + efectos de negocio)
se confirme o revierta atómicamente, sin que la capa de aplicación conozca SQLAlchemy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class UnitOfWork(ABC):
    @abstractmethod
    def commit(self) -> None:
        """Confirma la transacción actual."""

    @abstractmethod
    def rollback(self) -> None:
        """Revierte la transacción actual."""
