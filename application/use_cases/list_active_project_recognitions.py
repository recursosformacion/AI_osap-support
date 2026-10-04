"""Caso de uso: lectura M2M de reconocimientos vigentes de un proyecto (ADR-017).

Superficie `/api/v1/m2m/recognitions?project=…`: devuelve los reconocimientos ACTIVOS del
proyecto, de todos sus usuarios, **sin** filtrar por `public`. La fila `recognitions.public`
está deprecada: la visibilidad pública se decide por el consentimiento de cuenta
(`nickname_public_consent`, osap-auth) al recomponer la lista pública en osap-api.

Valida que el proyecto exista (whitelist). Nunca devuelve datos económicos ni origin/reason.

Nota: el aislamiento por cliente M2M (allowlist de proyectos del service client) vive en la
ruta; este caso de uso solo resuelve la lectura.
"""

from __future__ import annotations

from domain.entities import Recognition
from domain.exceptions import ProjectNotFoundError
from domain.ports.repositories import ProjectRepository, RecognitionRepository


class ListActiveProjectRecognitionsUseCase:
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
        return self._recognitions.list_active_by_project(project_slug)
