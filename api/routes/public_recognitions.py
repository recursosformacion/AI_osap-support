"""Ruta pública consentida: reconocimientos visibles de un tercero (ADR-015/008).

Excepción acotada de ADR-008: lectura de badges de otro usuario SOLO si el reconocimiento
está ACTIVE y el usuario dio consentimiento (`list_public`). Sin consentimiento el
reconocimiento no existe para terceros. Nunca se exponen datos económicos ni origin/reason.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.schemas.recognitions import PublicRecognitionItem
from application.use_cases.get_public_recognitions import GetPublicRecognitionsUseCase
from domain.exceptions import ProjectNotFoundError

router = APIRouter(prefix="/api/v1/public", tags=["public-recognitions"])


@router.get("/users/{user_id}/recognitions", response_model=list[PublicRecognitionItem])
def public_user_recognitions(
    user_id: str,
    project: str = Query(..., min_length=1),
) -> list[PublicRecognitionItem]:
    try:
        rows = _uc.execute(user_id=user_id, project_slug=project)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        PublicRecognitionItem(
            type=r.recognition_type.value,
            granted_at=r.granted_at,
        )
        for r in rows
    ]


# Wiring: use case con repositorios reales inyectado por api/main.py.
_uc: GetPublicRecognitionsUseCase


def wire_public_recognitions_router(uc: GetPublicRecognitionsUseCase) -> APIRouter:
    global _uc
    _uc = uc
    return router
