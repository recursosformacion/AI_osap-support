"""Rutas administrativas de reconocimientos (rol support:admin, ADR-015).

Frontera: el principal del token debe portar el rol `support:admin`; sin él → 403.
Listado con filtros, concesión (CONTRIBUTOR/VOICE) y revocación por id. Los routers son
adaptadores finos: toda la lógica vive en los use cases.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from api.schemas.recognitions import (
    AdminGrantRequest,
    AdminRecognitionItem,
    AdminRevokeRequest,
    AdminRevokeResponse,
)
from application.use_cases.admin_list_recognitions import AdminListRecognitionsUseCase
from application.use_cases.grant_recognition import GrantRecognitionUseCase
from application.use_cases.revoke_recognition import RevokeRecognitionUseCase
from domain.entities import RecognitionStatus, RecognitionType
from domain.exceptions import (
    InvalidGrantError,
    ProjectNotFoundError,
    RecognitionConflictError,
    RecognitionNotFoundError,
)
from domain.ports.identity import IdentityError, IdentityResolver
from domain.ports.repositories import RecognitionRepository

router = APIRouter(prefix="/api/v1/admin", tags=["admin-recognitions"])

_ADMIN_ROLE = "support:admin"


def _bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="autenticación requerida")
    return authorization.split(" ", 1)[1]


def _require_admin(bearer: str) -> str:
    try:
        principal = _identity.resolve_principal(bearer)
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    if _ADMIN_ROLE not in principal.roles:
        raise HTTPException(status_code=403, detail="rol support:admin requerido")
    return principal.user_id


def _parse_type(raw: str) -> RecognitionType:
    try:
        return RecognitionType(raw.strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"tipo desconocido: {raw}") from None


def _parse_status(raw: str | None) -> RecognitionStatus | None:
    if raw is None:
        return None
    try:
        return RecognitionStatus(raw.strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"estado desconocido: {raw}") from None


def _to_admin_item(recognition) -> AdminRecognitionItem:
    return AdminRecognitionItem(
        id=recognition.id if recognition.id is not None else -1,
        user_id=recognition.user_id,
        project=recognition.project_slug,
        type=recognition.recognition_type.value,
        kind=recognition.kind.value,
        status=recognition.status.value,
        granted_at=recognition.granted_at,
        granted_by=recognition.granted_by,
        origin=recognition.origin,
        reason=recognition.reason,
        active_until=recognition.active_until,
        public=recognition.public,
    )


@router.get("/recognitions", response_model=list[AdminRecognitionItem])
def admin_list_recognitions(
    user_id: str = Query(..., min_length=1),
    project: str | None = Query(default=None),
    type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    bearer: str = Depends(_bearer_token),
) -> list[AdminRecognitionItem]:
    _require_admin(bearer)
    rtype = _parse_type(type) if type is not None else None
    rstatus = _parse_status(status)
    rows = _list_uc.execute(
        user_id=user_id,
        project_slug=project,
        recognition_type=rtype,
        status=rstatus,
    )
    return [_to_admin_item(r) for r in rows]


@router.post("/recognitions", response_model=AdminRecognitionItem, status_code=201)
def admin_grant(
    body: AdminGrantRequest,
    bearer: str = Depends(_bearer_token),
) -> AdminRecognitionItem:
    admin_id = _require_admin(bearer)
    rtype = _parse_type(body.type)
    try:
        result = _grant_uc.execute(
            user_id=body.user_id,
            project_slug=body.project,
            recognition_type=rtype,
            granted_by=admin_id,
            reason=body.reason,
        )
    except InvalidGrantError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RecognitionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    recognition = _recognitions.get_current(
        body.user_id, body.project, result.recognition_type
    )
    if recognition is None:
        raise HTTPException(status_code=500, detail="reconocimiento no encontrado tras conceder")
    return _to_admin_item(recognition)


@router.post("/recognitions/{recognition_id}/revoke", response_model=AdminRevokeResponse)
def admin_revoke(
    recognition_id: int,
    body: AdminRevokeRequest,
    bearer: str = Depends(_bearer_token),
) -> AdminRevokeResponse:
    admin_id = _require_admin(bearer)
    try:
        result = _revoke_uc.execute(
            recognition_id=recognition_id,
            granted_by=admin_id,
            reason=body.reason,
        )
    except RecognitionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return AdminRevokeResponse(
        recognition_id=result.recognition_id, changed=result.changed
    )


# Wiring: bootstrap (api/main.py) inyecta identity, repositorio y use cases.
_identity: IdentityResolver
_recognitions: RecognitionRepository
_list_uc: AdminListRecognitionsUseCase
_grant_uc: GrantRecognitionUseCase
_revoke_uc: RevokeRecognitionUseCase


def wire_admin_recognitions_router(
    *,
    identity: IdentityResolver,
    recognitions: RecognitionRepository,
    list_uc: AdminListRecognitionsUseCase,
    grant_uc: GrantRecognitionUseCase,
    revoke_uc: RevokeRecognitionUseCase,
) -> APIRouter:
    global _identity, _recognitions, _list_uc, _grant_uc, _revoke_uc
    _identity = identity
    _recognitions = recognitions
    _list_uc = list_uc
    _grant_uc = grant_uc
    _revoke_uc = revoke_uc
    return router
