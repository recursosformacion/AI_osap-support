"""Fake EmailSender para tests (Fase 7).

Registra cada envío en memoria para que los tests puedan verificar: qué emails se
intentaron, destinatario, template, número de envíos. NO hace conexiones externas y NO
es una implementación productiva (el proveedor de email está ABIERTO).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from domain.ports.email import EmailMessage, EmailSender


@dataclass(frozen=True)
class SentEmail:
    template: str
    recipient_email: str
    origin_event_ref: str | None = None
    context: dict[str, object] = field(default_factory=dict)


class FakeEmailSender(EmailSender):
    """Enviador ficticio determinista para tests."""

    def __init__(self) -> None:
        self.sent: list[SentEmail] = []
        self.fail_next: int = 0  # nº de envíos que fallarán (para probar fallo)

    def send(self, message: EmailMessage) -> bool:
        if self.fail_next > 0:
            self.fail_next -= 1
            return False
        self.sent.append(
            SentEmail(
                template=message.template,
                recipient_email=message.recipient_email,
                origin_event_ref=message.origin_event_ref,
                context=dict(message.context),
            )
        )
        return True
