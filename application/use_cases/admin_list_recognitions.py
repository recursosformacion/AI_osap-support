"""Caso de uso: listado administrativo de reconocimientos (ADMIN, ADR-015).

El admin consulta reconocimientos de un usuario/proyecto con filtros opcionales por tipo y
estado. Es una consulta de auditoría/gestión; los filtros viven aquí (no en HTTP).
"""

from __future__ import annotations

from domain.entities import Recognition, RecognitionStatus, RecognitionType
from domain.ports.repositories import RecognitionRepository


class AdminListRecognitionsUseCase:
    def __init__(self, *, recognitions: RecognitionRepository) -> None:
        self._recognitions = recognitions

    def execute(
        self,
        *,
        user_id: str,
        project_slug: str | None = None,
        recognition_type: RecognitionType | None = None,
        status: RecognitionStatus | None = None,
    ) -> list[Recognition]:
        rows = self._recognitions.list_by_user(user_id, project_slug)
        if recognition_type is not None:
            rows = [r for r in rows if r.recognition_type is recognition_type]
        if status is not None:
            rows = [r for r in rows if r.status is status]
        return rows
