"""Caso de uso: ingesta M2M de una contribución agregada (ADR-017).

Contrato OMR → Support: el emisor (autenticado por service token en la capa HTTP) envía un
delta aditivo con `source_reference` idempotente. Este caso de uso:
1. rechaza duplicados (UNIQUE source+source_reference) sin re-derivar;
2. valida que el proyecto exista (whitelist);
3. garantiza `support_members`;
4. persiste la contribución y evalúa CONTRIBUTOR en la misma transacción.
El `source` no viaja en el body: lo fija la capa HTTP a partir del client autenticado.
"""

from __future__ import annotations

from dataclasses import dataclass

from application.use_cases.evaluate_contributor import EvaluateContributorRecognitionUseCase
from domain.entities import Contribution, ContributionType, SupportMember
from domain.exceptions import ProjectNotFoundError
from domain.ports.clock import Clock
from domain.ports.repositories import (
    ContributionRepository,
    ProjectRepository,
    SupportMemberRepository,
)
from domain.ports.unit_of_work import UnitOfWork


@dataclass(frozen=True)
class ContributionIngestResult:
    outcome: str  # created | duplicate
    contribution_id: int | None
    contributor_active: bool


class IngestContributionUseCase:
    def __init__(
        self,
        *,
        contributions: ContributionRepository,
        projects: ProjectRepository,
        support_members: SupportMemberRepository,
        contributor_evaluator: EvaluateContributorRecognitionUseCase,
        clock: Clock,
        uow: UnitOfWork,
    ) -> None:
        self._contributions = contributions
        self._projects = projects
        self._support_members = support_members
        self._contributor_evaluator = contributor_evaluator
        self._clock = clock
        self._uow = uow

    def execute(
        self,
        *,
        user_id: str,
        project_slug: str,
        contribution_type: ContributionType,
        summary: str,
        source: str,
        source_reference: str,
        amount: int | None = None,
    ) -> ContributionIngestResult:
        existing = self._contributions.get_by_idempotency_key(source, source_reference)
        if existing is not None:
            return ContributionIngestResult(
                outcome="duplicate", contribution_id=existing.id, contributor_active=False
            )

        if self._projects.get_by_slug(project_slug) is None:
            raise ProjectNotFoundError(f"proyecto desconocido: {project_slug}")
        self._ensure_support_member(user_id)

        contribution = Contribution(
            id=None,
            user_id=user_id,
            project_slug=project_slug,
            contribution_type=contribution_type,
            summary=summary,
            amount=amount,
            source=source,
            source_reference=source_reference,
            created_at=self._clock.utc_now(),
        )
        contribution = self._contributions.add(contribution)

        # Derivación CONTRIBUTOR en la misma transacción (sin commit intermedio).
        evaluation = self._contributor_evaluator.execute(
            user_id, project_slug, commit=False
        )
        self._uow.commit()
        return ContributionIngestResult(
            outcome="created",
            contribution_id=contribution.id,
            contributor_active=evaluation.active,
        )

    def _ensure_support_member(self, user_id: str) -> None:
        if not self._support_members.exists(user_id):
            self._support_members.add(SupportMember(user_id=user_id))
