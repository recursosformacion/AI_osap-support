"""Caso de uso: listar los reconocimientos del propio usuario (ADR-008).

El user_id llega ya resuelto desde el token (la capa HTTP resuelve la identidad). Opcional:
filtro por proyecto. Incluye todos los estados (ACTIVE e INACTIVE/histórico); la decisión de
qué mostrar en público es del lector público consentido (otro caso de uso/superficie).
"""

from __future__ import annotations

from domain.entities import Recognition
from domain.ports.repositories import RecognitionRepository


class ListMyRecognitionsUseCase:
    def __init__(self, *, recognitions: RecognitionRepository) -> None:
        self._recognitions = recognitions

    def execute(
        self, user_id: str, project_slug: str | None = None
    ) -> list[Recognition]:
        return self._recognitions.list_by_user(user_id, project_slug)
