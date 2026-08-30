"""Caso de uso: worker de CommunicationEvent pendientes (Fase 7).

Flujo (ADR-006, V-010): CommunicationEvent pendiente → worker → EmailSender → marcar
enviado/fallido. NO envía emails directamente desde el webhook; NO hay proveedor real.

- Idempotencia: solo procesa eventos con status=pending y next_attempt_at vencido.
- Fallo: no marca como enviado; incrementa attempts y aplica backoff (reintentable).
- Varios eventos: se procesan individualmente; un fallo no descarta los demás
  (commit por evento vía UnitOfWork).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from domain.entities import CommunicationEvent, CommunicationEventStatus
from domain.ports.email import EmailMessage, EmailSender
from domain.ports.repositories import CommunicationEventRepository
from domain.ports.unit_of_work import UnitOfWork

_BACKOFF_MINUTES = 5


@dataclass(frozen=True)
class WorkerSummary:
    processed: int = 0
    sent: int = 0
    failed: int = 0


class ProcessCommunicationEventsUseCase:
    def __init__(
        self,
        *,
        communications: CommunicationEventRepository,
        email_sender: EmailSender,
        uow: UnitOfWork,
    ) -> None:
        self._communications = communications
        self._email_sender = email_sender
        self._uow = uow

    def execute(self, limit: int = 100) -> WorkerSummary:
        pending = self._communications.list_pending()[:limit]
        summary = WorkerSummary(processed=len(pending))
        for event in pending:
            self._process_one(event)
            sent_inc = 1 if event.status == CommunicationEventStatus.SENT else 0
            failed_inc = 1 if event.status == CommunicationEventStatus.FAILED else 0
            summary = WorkerSummary(
                processed=summary.processed,
                sent=summary.sent + sent_inc,
                failed=summary.failed + failed_inc,
            )
        return summary

    def _process_one(self, event: CommunicationEvent) -> None:
        message = EmailMessage(
            template=event.template,
            recipient_email=event.recipient_email,
            origin_event_ref=str(event.id) if event.id is not None else None,
        )
        try:
            accepted = self._email_sender.send(message)
        except Exception:
            accepted = False
        now = datetime.now(UTC)
        event.attempts += 1
        if accepted:
            event.status = CommunicationEventStatus.SENT
            event.sent_at = now
            event.last_error = None
        else:
            event.status = CommunicationEventStatus.FAILED
            event.next_attempt_at = now + timedelta(minutes=_BACKOFF_MINUTES * event.attempts)
            event.last_error = "envío rechazado"
        self._communications.update(event)
        self._uow.commit()
