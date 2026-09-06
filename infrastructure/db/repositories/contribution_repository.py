"""Repositorio SQLAlchemy de Contribution (ADR-017).

`UNIQUE(source, source_reference)` garantiza la idempotencia del contrato M2M incluso bajo
concurrencia: IntegrityError se traduce a `DuplicateContributionError` (patrón del repo de
PaymentEvent/ADR-007). El dominio opera con `project_slug`; aquí se resuelve el `projects.id`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from domain.entities import Contribution, ContributionType
from domain.exceptions import DuplicateContributionError, ProjectNotFoundError
from domain.ports.repositories import ContributionRepository
from infrastructure.db.models import ContributionModel, ProjectModel


class SqlAlchemyContributionRepository(ContributionRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, contribution: Contribution) -> Contribution:
        model = self._to_model(contribution)
        self._session.add(model)
        try:
            self._session.flush()
        except IntegrityError as exc:
            self._session.rollback()
            raise DuplicateContributionError(
                f"contribución duplicada ({contribution.source}, "
                f"{contribution.source_reference})"
            ) from exc
        contribution.id = model.id
        return contribution

    def get_by_idempotency_key(
        self, source: str, source_reference: str
    ) -> Contribution | None:
        model = self._session.execute(
            select(ContributionModel).where(
                ContributionModel.source == source,
                ContributionModel.source_reference == source_reference,
            )
        ).scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    def list_by_user_project(self, user_id: str, project_slug: str) -> list[Contribution]:
        models = self._session.execute(
            select(ContributionModel)
            .join(ProjectModel, ContributionModel.project_id == ProjectModel.id)
            .where(
                ContributionModel.user_id == user_id,
                ProjectModel.slug == project_slug,
            )
            .order_by(ContributionModel.id)
        ).scalars().all()
        return [self._to_domain(m) for m in models]

    def sum_amount(
        self,
        user_id: str,
        project_slug: str,
        contribution_types: frozenset[ContributionType],
    ) -> int:
        """Suma de deltas del bucket en SQL (espejo de `bucket_total` del dominio)."""
        type_values = [t.value for t in contribution_types]
        total = self._session.execute(
            select(func.coalesce(func.sum(ContributionModel.amount), 0))
            .join(ProjectModel, ContributionModel.project_id == ProjectModel.id)
            .where(
                ContributionModel.user_id == user_id,
                ProjectModel.slug == project_slug,
                ContributionModel.type.in_(type_values),
            )
        ).scalar_one()
        return int(total or 0)

    def _to_model(self, contribution: Contribution) -> ContributionModel:
        project_id = self._session.execute(
            select(ProjectModel.id).where(ProjectModel.slug == contribution.project_slug)
        ).scalar_one_or_none()
        if project_id is None:
            raise ProjectNotFoundError(f"proyecto desconocido: {contribution.project_slug}")
        return ContributionModel(
            id=contribution.id,
            user_id=contribution.user_id,
            project_id=project_id,
            type=contribution.contribution_type.value,
            summary=contribution.summary,
            amount=contribution.amount,
            source=contribution.source,
            source_reference=contribution.source_reference,
            created_at=contribution.created_at,
        )

    @staticmethod
    def _to_domain(model: ContributionModel) -> Contribution:
        return Contribution(
            id=model.id,
            user_id=model.user_id,
            project_slug=model.project.slug,
            contribution_type=ContributionType(model.type),
            summary=model.summary,
            amount=model.amount,
            source=model.source,
            source_reference=model.source_reference,
            created_at=model.created_at,
        )
