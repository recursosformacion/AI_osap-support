"""Repositorio SQLAlchemy de PaymentEvent.

ADR-007: `UNIQUE(provider, provider_event_id)` garantiza idempotencia incluso bajo
concurrencia. El repositorio captura IntegrityError y lo traduce a
`DuplicatePaymentEventError` (concepto de dominio).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain.entities import PaymentEvent, PaymentEventStatus
from domain.exceptions import DuplicatePaymentEventError
from domain.ports.repositories import PaymentEventRepository
from infrastructure.db.models import PaymentEventModel


class SqlAlchemyPaymentEventRepository(PaymentEventRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: PaymentEvent) -> PaymentEvent:
        model = self._to_model(event)
        self._session.add(model)
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise DuplicatePaymentEventError(
                f"evento duplicado ({event.provider}, {event.provider_event_id})"
            ) from exc
        event.id = model.id
        return event

    def get_by_idempotency_key(self, provider: str, provider_event_id: str) -> PaymentEvent | None:
        model = self._session.execute(
            select(PaymentEventModel).where(
                PaymentEventModel.provider == provider,
                PaymentEventModel.provider_event_id == provider_event_id,
            )
        ).scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    def _to_model(self, e: PaymentEvent) -> PaymentEventModel:
        return PaymentEventModel(
            id=e.id,
            provider=e.provider,
            provider_event_id=e.provider_event_id,
            event_type=e.event_type,
            user_id=e.user_id,
            payload_hash=e.payload_hash,
            status=e.status.value,
            received_at=e.received_at,
            processed_at=e.processed_at,
        )

    def _to_domain(self, model: PaymentEventModel) -> PaymentEvent:
        return PaymentEvent(
            id=model.id,
            provider=model.provider,
            provider_event_id=model.provider_event_id,
            event_type=model.event_type,
            user_id=model.user_id,
            payload_hash=model.payload_hash,
            status=PaymentEventStatus(model.status),
            received_at=model.received_at,
            processed_at=model.processed_at,
        )
