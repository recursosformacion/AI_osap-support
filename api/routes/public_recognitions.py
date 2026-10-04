"""Ruta pública consentida: reconocimientos visibles de un tercero (ADR-015/008).

DEPRECADA. La visibilidad pública ya no depende de la fila `recognitions.public` (deprecada,
sin migración destructiva): pasa a ser autorización **de cuenta** vía
`nickname_public_consent` (osap-auth). La única surface pública vigente es
`GET /api/v1/public/collaborators` de osap-api, que compone support M2M + auth M2M y nunca
expone `user_id`. Estas rutas se conservan solo por compatibilidad y se retirarán.

Excepción acotada de ADR-008: lectura de badges de otro usuario SOLO si el reconocimiento
está ACTIVE y el usuario dio consentimiento (`list_public`). Sin consentimiento el
reconocimiento no existe para terceros. Nunca se exponen datos económicos ni origin/reason.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.schemas.recognitions import PublicProjectUserRecognitions, PublicRecognitionItem
from application.use_cases.get_public_recognitions import GetPublicRecognitionsUseCase
from application.use_cases.list_public_project_recognitions import (
    ListPublicProjectRecognitionsUseCase,
)
from domain.exceptions import ProjectNotFoundError

router = APIRouter(prefix="/api/v1/public", tags=["public-recognitions"])


@router.get(
    "/users/{user_id}/recognitions",
    response_model=list[PublicRecognitionItem],
    deprecated=True,
)
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


@router.get(
    "/projects/{project}/recognitions",
    response_model=list[PublicProjectUserRecognitions],
    deprecated=True,
)
def public_project_recognitions(project: str) -> list[PublicProjectUserRecognitions]:
    try:
        rows = _project_uc.execute(project_slug=project)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    agrupado: dict[str, list[PublicRecognitionItem]] = {}
    for r in rows:
        agrupado.setdefault(r.user_id, []).append(
            PublicRecognitionItem(type=r.recognition_type.value, granted_at=r.granted_at)
        )
    return [
        PublicProjectUserRecognitions(user_id=user_id, recognitions=items)
        for user_id, items in agrupado.items()
    ]


# Wiring: use cases con repositorios reales inyectados por api/main.py.
_uc: GetPublicRecognitionsUseCase
_project_uc: ListPublicProjectRecognitionsUseCase


def wire_public_recognitions_router(
    uc: GetPublicRecognitionsUseCase,
    project_uc: ListPublicProjectRecognitionsUseCase,
) -> APIRouter:
    global _uc, _project_uc
    _uc = uc
    _project_uc = project_uc
    return router
