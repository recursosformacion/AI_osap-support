"""Caso de uso: lectura pública consentida de reconocimientos de un proyecto (ADR-015).

Superficie `/public/projects/{project}/recognitions`: devuelve SOLO reconocimientos ACTIVOS con
consentimiento (`list_public_by_project`), de todos los usuarios del proyecto. Valida que el
proyecto exista (whitelist). Nunca devuelve datos económicos ni origin/reason.
"""

from __future__ import annotations

from domain.entities import Recognition
from domain.exceptions import ProjectNotFoundError
from domain.ports.repositories import ProjectRepository, RecognitionRepository


class ListPublicProjectRecognitionsUseCase:
    def __init__(
        self,
        *,
        recognitions: RecognitionRepository,
        projects: ProjectRepository,
    ) -> None:
        self._recognitions = recognitions
        self._projects = projects

    def execute(self, project_slug: str) -> list[Recognition]:
        if self._projects.get_by_slug(project_slug) is None:
            raise ProjectNotFoundError(f"proyecto desconocido: {project_slug}")
        return self._recognitions.list_public_by_project(project_slug)
