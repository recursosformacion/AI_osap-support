"""Rutas de usuario: reconocimientos propios y consentimiento (ADR-008/015).

Adaptador HTTP fino: autenticación (token → user_id) → validación DTO → use case →
respuesta. No decide quién es Supporter/Contributor/etc.: eso lo hacen las reglas del
dominio y los use cases.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from api.schemas.recognitions import (
    RecognitionConsentRequest,
    RecognitionConsentResponse,
    RecognitionMeItem,
)
from application.use_cases.list_my_recognitions import ListMyRecognitionsUseCase
from application.use_cases.set_recognition_consent import SetRecognitionConsentUseCase
from domain.entities import RecognitionType
from domain.exceptions import RecognitionNotFoundError
from domain.ports.identity import IdentityError, IdentityResolver

router = APIRouter(prefix="/api/v1", tags=["recognitions"])


def _bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="autenticación requerida")
    return authorization.split(" ", 1)[1]


def _current_user(bearer: str) -> str:
    try:
        return _identity.resolve_user_id(bearer)
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _parse_type(raw: str) -> RecognitionType:
    try:
        return RecognitionType(raw.strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"tipo desconocido: {raw}") from None


def _to_me_item(recognition) -> RecognitionMeItem:
    return RecognitionMeItem(
        type=recognition.recognition_type.value,
        kind=recognition.kind.value,
        status=recognition.status.value,
        granted_at=recognition.granted_at,
        active_until=recognition.active_until,
        public=recognition.public,
    )


@router.get("/recognitions/me", response_model=list[RecognitionMeItem])
def my_recognitions(
    bearer: str = Depends(_bearer_token),
    project: str | None = Query(default=None),
) -> list[RecognitionMeItem]:
    user_id = _current_user(bearer)
    rows = _list_uc.execute(user_id, project_slug=project)
    return [_to_me_item(r) for r in rows]


@router.put("/recognitions/me/consent", response_model=RecognitionConsentResponse)
def consent(
    body: RecognitionConsentRequest,
    bearer: str = Depends(_bearer_token),
) -> RecognitionConsentResponse:
    user_id = _current_user(bearer)
    rtype = _parse_type(body.type)
    try:
        result = _consent_uc.execute(
            user_id=user_id,
            project_slug=body.project,
            recognition_type=rtype,
            public=body.public,
        )
    except RecognitionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RecognitionConsentResponse(
        project=result.project_slug,
        type=result.recognition_type.value,
        public=result.public,
        changed=result.changed,
    )


# Wiring: el bootstrap (api/main.py) inyecta identity y use cases reales.
_identity: IdentityResolver
_list_uc: ListMyRecognitionsUseCase
_consent_uc: SetRecognitionConsentUseCase


def wire_recognitions_router(
    identity: IdentityResolver,
    list_uc: ListMyRecognitionsUseCase,
    consent_uc: SetRecognitionConsentUseCase,
) -> APIRouter:
    global _identity, _list_uc, _consent_uc
    _identity = identity
    _list_uc = list_uc
    _consent_uc = consent_uc
    return router
