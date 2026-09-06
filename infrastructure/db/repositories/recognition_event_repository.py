"""Repositorio SQLAlchemy de RecognitionEvent (historial inmutable, ADR-016).

Apendice al libro mayor de reconocimientos; nunca se actualiza ni elimina una fila. El
dominio opera con `project_slug` (resuelto vía join con `projects`).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entities import (
    RecognitionEvent,
    RecognitionEventType,
    RecognitionStatus,
    RecognitionType,
)
from domain.exceptions import ProjectNotFoundError
from domain.ports.repositories import RecognitionEventRepository
from infrastructure.db.models import ProjectModel, RecognitionEventModel


class SqlAlchemyRecognitionEventRepository(RecognitionEventRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, event: RecognitionEvent) -> RecognitionEvent:
        model = self._to_model(event)
        self._session.add(model)
        self._session.flush()
        event.id = model.id
        return event

    def list_by_user(self, user_id: str) -> list[RecognitionEvent]:
        models = self._session.execute(
            select(RecognitionEventModel)
            .join(ProjectModel, RecognitionEventModel.project_id == ProjectModel.id)
            .where(RecognitionEventModel.user_id == user_id)
            .order_by(RecognitionEventModel.id)
        ).scalars().all()
        return [self._to_domain(m) for m in models]

    def _to_model(self, event: RecognitionEvent) -> RecognitionEventModel:
        project_id = self._session.execute(
            select(ProjectModel.id).where(ProjectModel.slug == event.project_slug)
        ).scalar_one_or_none()
        if project_id is None:
            raise ProjectNotFoundError(f"proyecto desconocido: {event.project_slug}")
        return RecognitionEventModel(
            id=event.id,
            user_id=event.user_id,
            project_id=project_id,
            type=event.recognition_type.value,
            event_type=event.event_type.value,
            status_after=event.status_after.value,
            reason=event.reason,
            origin=event.origin,
            origin_ref=event.origin_ref,
            granted_by=event.granted_by,
            occurred_at=event.occurred_at,
        )

    @staticmethod
    def _to_domain(model: RecognitionEventModel) -> RecognitionEvent:
        return RecognitionEvent(
            id=model.id,
            user_id=model.user_id,
            project_slug=model.project.slug,
            recognition_type=RecognitionType(model.type),
            event_type=RecognitionEventType(model.event_type),
            status_after=RecognitionStatus(model.status_after),
            reason=model.reason,
            origin=model.origin,
            origin_ref=model.origin_ref,
            granted_by=model.granted_by,
            occurred_at=model.occurred_at,
        )
