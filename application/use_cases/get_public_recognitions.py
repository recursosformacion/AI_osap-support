"""Caso de uso: lectura pública consentida de reconocimientos (ADR-015).

Superficie `/public/users/{user_id}/recognitions`: un tercero solo puede ver los
reconocimientos ACTIVOS con consentimiento (`list_public`). Valida además que el proyecto
exista (whitelist). Nunca devuelve datos económicos.
"""

from __future__ import annotations

from domain.entities import Recognition
from domain.exceptions import ProjectNotFoundError
from domain.ports.repositories import (
    ProjectRepository,
    RecognitionRepository,
)


class GetPublicRecognitionsUseCase:
    def __init__(
        self,
        *,
        recognitions: RecognitionRepository,
        projects: ProjectRepository,
    ) -> None:
        self._recognitions = recognitions
        self._projects = projects

    def execute(
        self, user_id: str, project_slug: str
    ) -> list[Recognition]:
        if self._projects.get_by_slug(project_slug) is None:
            raise ProjectNotFoundError(f"proyecto desconocido: {project_slug}")
        return self._recognitions.list_public(user_id, project_slug)
