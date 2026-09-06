"""Repositorio SQLAlchemy de Recognition (proyección de estado, ADR-015).

Una fila por (user_id, project_id, type) con UNIQUE uq_recognition_current. El dominio
opera con `project_slug`; la infraestructura resuelve el `projects.id` (FK) y devuelve el
slug vía join al leer. `add` crea (clave natural libre); `update` persiste cambios
(estado/consentimiento) sobre la fila existente vía merge.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entities import (
    Recognition,
    RecognitionKind,
    RecognitionStatus,
    RecognitionType,
)
from domain.exceptions import ProjectNotFoundError
from domain.ports.repositories import RecognitionRepository
from infrastructure.db.models import ProjectModel, RecognitionModel


class SqlAlchemyRecognitionRepository(RecognitionRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, recognition: Recognition) -> Recognition:
        model = self._to_model(recognition)
        self._session.add(model)
        self._session.flush()
        recognition.id = model.id
        return recognition

    def update(self, recognition: Recognition) -> Recognition:
        model = self._to_model(recognition)
        self._session.merge(model)
        self._session.flush()
        return recognition

    def get_current(
        self, user_id: str, project_slug: str, recognition_type: RecognitionType
    ) -> Recognition | None:
        model = self._session.execute(
            select(RecognitionModel)
            .join(ProjectModel, RecognitionModel.project_id == ProjectModel.id)
            .where(
                RecognitionModel.user_id == user_id,
                ProjectModel.slug == project_slug,
                RecognitionModel.type == recognition_type.value,
            )
        ).scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    def get_by_id(self, recognition_id: int) -> Recognition | None:
        model = self._session.execute(
            select(RecognitionModel).where(RecognitionModel.id == recognition_id)
        ).scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    def list_by_user(
        self, user_id: str, project_slug: str | None = None
    ) -> list[Recognition]:
        stmt = select(RecognitionModel).join(
            ProjectModel, RecognitionModel.project_id == ProjectModel.id
        )
        conditions = [RecognitionModel.user_id == user_id]
        if project_slug is not None:
            conditions.append(ProjectModel.slug == project_slug)
        stmt = stmt.where(*conditions)
        models = self._session.execute(stmt).scalars().all()
        return [self._to_domain(m) for m in models]

    def list_public(
        self, user_id: str, project_slug: str | None = None
    ) -> list[Recognition]:
        """Lectura pública consentida (ADR-015): SOLO ACTIVE y public=true."""
        stmt = select(RecognitionModel).join(
            ProjectModel, RecognitionModel.project_id == ProjectModel.id
        )
        conditions = [
            RecognitionModel.user_id == user_id,
            RecognitionModel.status == RecognitionStatus.ACTIVE.value,
            RecognitionModel.public.is_(True),
        ]
        if project_slug is not None:
            conditions.append(ProjectModel.slug == project_slug)
        stmt = stmt.where(*conditions).order_by(RecognitionModel.id)
        models = self._session.execute(stmt).scalars().all()
        return [self._to_domain(m) for m in models]

    def _to_model(self, recognition: Recognition) -> RecognitionModel:
        project_id = self._session.execute(
            select(ProjectModel.id).where(ProjectModel.slug == recognition.project_slug)
        ).scalar_one_or_none()
        if project_id is None:
            raise ProjectNotFoundError(f"proyecto desconocido: {recognition.project_slug}")
        return RecognitionModel(
            id=recognition.id,
            user_id=recognition.user_id,
            project_id=project_id,
            type=recognition.recognition_type.value,
            kind=recognition.kind.value,
            status=recognition.status.value,
            granted_at=recognition.granted_at,
            granted_by=recognition.granted_by,
            origin=recognition.origin,
            reason=recognition.reason,
            active_until=recognition.active_until,
            public=recognition.public,
            public_since=recognition.public_since,
            public_revoked_at=recognition.public_revoked_at,
            created_at=recognition.created_at,
            updated_at=recognition.updated_at,
        )

    @staticmethod
    def _to_domain(model: RecognitionModel) -> Recognition:
        return Recognition(
            id=model.id,
            user_id=model.user_id,
            project_slug=model.project.slug,
            recognition_type=RecognitionType(model.type),
            kind=RecognitionKind(model.kind),
            status=RecognitionStatus(model.status),
            granted_at=model.granted_at,
            granted_by=model.granted_by,
            origin=model.origin,
            reason=model.reason,
            active_until=model.active_until,
            public=model.public,
            public_since=model.public_since,
            public_revoked_at=model.public_revoked_at,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
