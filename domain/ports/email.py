"""Puerto de email — ADR-006 (V-010 FIJADA).

Support es propietario de las comunicaciones de la relación económica. El flujo previsto
es `PaymentEvent → CommunicationEvent → worker → EmailSender`. Este port NO se implementa
en esta fase; queda como frontera. NUNCA `webhook → email directo`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class EmailMessage:
    template: str  # clave de plantilla (welcome, thanks, renewal, ...)
    recipient_email: str
    origin_event_ref: str | None = None  # referencia al CommunicationEvent/PaymentEvent
    subject: str | None = None
    body: str | None = None
    html: str | None = None
    context: dict[str, object] = field(default_factory=dict)


class EmailSender(ABC):
    """Frontera conceptual del proveedor de email (no implementado todavía)."""

    @abstractmethod
    def send(self, message: EmailMessage) -> bool:
        """Envía un email. Devuelve True si se acepta; lanza en fallo controlado."""


def utc_now() -> datetime:
    return datetime.now(UTC)
