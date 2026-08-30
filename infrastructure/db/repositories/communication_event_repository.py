"""Repositorio SQLAlchemy de CommunicationEvent (mapeo persistencia <-> dominio)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entities import CommunicationEvent, CommunicationEventStatus
from domain.ports.repositories import CommunicationEventRepository
from infrastructure.db.models import CommunicationEventModel


class SqlAlchemyCommunicationEventRepository(CommunicationEventRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: CommunicationEvent) -> CommunicationEvent:
        model = self._to_model(event)
        self._session.add(model)
        self._session.flush()
        event.id = model.id
        return event

    def get(self, event_id: int) -> CommunicationEvent | None:
        model = self._session.get(CommunicationEventModel, event_id)
        return self._to_domain(model) if model is not None else None

    def list_by_user(self, user_id: str) -> list[CommunicationEvent]:
        models = self._session.execute(
            select(CommunicationEventModel).where(CommunicationEventModel.user_id == user_id)
        ).scalars().all()
        return [self._to_domain(m) for m in models]

    def list_pending(self) -> list[CommunicationEvent]:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        retryable = [
            CommunicationEventStatus.PENDING.value,
            CommunicationEventStatus.FAILED.value,
        ]
        models = (
            self._session.execute(
                select(CommunicationEventModel).where(
                    CommunicationEventModel.status.in_(retryable),
                    (CommunicationEventModel.next_attempt_at.is_(None))
                    | (CommunicationEventModel.next_attempt_at <= now),
                )
            )
            .scalars()
            .all()
        )
        return [self._to_domain(m) for m in models]

    def update(self, event: CommunicationEvent) -> CommunicationEvent:
        self._session.merge(self._to_model(event))
        self._session.flush()
        return event

    def _to_model(self, e: CommunicationEvent) -> CommunicationEventModel:
        return CommunicationEventModel(
            id=e.id,
            user_id=e.user_id,
            template=e.template,
            recipient_email=e.recipient_email,
            status=e.status.value,
            attempts=e.attempts,
            next_attempt_at=e.next_attempt_at,
            origin_event_id=e.origin_event_id,
            created_at=e.created_at,
            sent_at=e.sent_at,
            last_error=e.last_error,
        )

    def _to_domain(self, model: CommunicationEventModel) -> CommunicationEvent:
        return CommunicationEvent(
            id=model.id,
            user_id=model.user_id,
            template=model.template,
            recipient_email=model.recipient_email,
            status=CommunicationEventStatus(model.status),
            attempts=model.attempts,
            next_attempt_at=model.next_attempt_at,
            origin_event_id=model.origin_event_id,
            created_at=model.created_at,
            sent_at=model.sent_at,
            last_error=model.last_error,
        )
