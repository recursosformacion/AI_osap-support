"""Ruta M2M de reconocimientos vigentes por proyecto (ADR-017).

`osap-support` es la fuente de verdad de los reconocimientos; esta ruta permite a `osap-api`
componer la lista pública de colaboradores sin exponer `user_id` al navegador y sin depender
de la fila deprecada `recognitions.public`: devuelve los reconocimientos ACTIVOS del proyecto y
la visibilidad la decide el consentimiento de cuenta (`nickname_public_consent`, osap-auth).

Contrato:
  GET /api/v1/m2m/recognitions?project=<slug>
  → [ { "user_id": …, "recognitions": [ { "type": …, "granted_at": … } ] } ]

Autorización (mismo mecanismo M2M que membresía/contribuciones): service token válido con el
scope requerido (por defecto `api:read`, configurable con
`OSAP_SUPPORT_M2M_RECOGNITIONS_SCOPE`), client_id presente en la allowlist `[m2m]` y proyecto
dentro de la allowlist de ese client. Sin lógica de negocio ni SQL aquí: delega en
`ListActiveProjectRecognitionsUseCase`.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from api.schemas.recognitions import ActiveProjectUserRecognitions, PublicRecognitionItem
from application.use_cases.list_active_project_recognitions import (
    ListActiveProjectRecognitionsUseCase,
)
from domain.exceptions import ProjectNotFoundError
from domain.ports.identity import (
    IdentityError,
    ServiceAuthenticator,
    ServiceScopeError,
)
from infrastructure.config import M2mClientConfig

router = APIRouter(prefix="/api/v1/m2m", tags=["m2m-recognitions"])

# Scope de LECTURA existente; configurable para apuntar a uno dedicado sin cambiar código.
_REQUIRED_SCOPE = os.environ.get("OSAP_SUPPORT_M2M_RECOGNITIONS_SCOPE", "api:read")


def _bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="autenticación requerida")
    return authorization.split(" ", 1)[1]


@router.get("/recognitions", response_model=list[ActiveProjectUserRecognitions])
def project_recognitions(
    project: str = Query(..., min_length=1),
    bearer: str = Depends(_bearer_token),
) -> list[ActiveProjectUserRecognitions]:
    try:
        service = _service_authenticator.authenticate_service(
            bearer, required_scope=_REQUIRED_SCOPE
        )
    except ServiceScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    scope = _m2m_scope(service.client_id)
    if scope is None:
        raise HTTPException(status_code=403, detail="client M2M no permitido")
    if project not in scope.projects:
        raise HTTPException(
            status_code=403,
            detail=f"proyecto no permitido para este client: {project}",
        )

    try:
        rows = _uc.execute(project)
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    agrupado: dict[str, list[PublicRecognitionItem]] = {}
    for r in rows:
        agrupado.setdefault(r.user_id, []).append(
            PublicRecognitionItem(type=r.recognition_type.value, granted_at=r.granted_at)
        )
    return [
        ActiveProjectUserRecognitions(user_id=user_id, recognitions=items)
        for user_id, items in agrupado.items()
    ]


# Wiring inyectado por el bootstrap (api/main.py).
_service_authenticator: ServiceAuthenticator
_m2m_scope: Callable[[str], M2mClientConfig | None]
_uc: ListActiveProjectRecognitionsUseCase


def wire_m2m_recognitions_router(
    *,
    service_authenticator: ServiceAuthenticator,
    m2m_scope: Callable[[str], M2mClientConfig | None],
    list_uc: ListActiveProjectRecognitionsUseCase,
) -> APIRouter:
    global _service_authenticator, _m2m_scope, _uc
    _service_authenticator = service_authenticator
    _m2m_scope = m2m_scope
    _uc = list_uc
    return router
