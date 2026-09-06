"""Repositorio SQLAlchemy de Project (registro whitelisted, ADR-015).

Mapeo persistencia <-> dominio: `slug` es el identificador canónico del dominio; `id`
(surrogate) queda dentro de la infraestructura.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entities import Project
from domain.ports.repositories import ProjectRepository
from infrastructure.db.models import ProjectModel


class SqlAlchemyProjectRepository(ProjectRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_slug(self, slug: str) -> Project | None:
        model = self._session.execute(
            select(ProjectModel).where(ProjectModel.slug == slug)
        ).scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    def add(self, project: Project) -> Project:
        model = ProjectModel(slug=project.slug, name=project.name, created_at=project.created_at)
        self._session.add(model)
        self._session.flush()
        return project

    @staticmethod
    def _to_domain(model: ProjectModel) -> Project:
        return Project(slug=model.slug, name=model.name, created_at=model.created_at)
