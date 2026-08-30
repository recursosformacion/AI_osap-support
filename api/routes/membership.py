"""Rutas de usuario de OSAP Support (Fase 5).

Adaptador HTTP: no contiene lógica de negocio ni SQL. Delega en el caso de uso.
La identidad se deriva del token (ADR-008: nunca de un `user_id` en la URL).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException

from api.schemas.membership import MembershipMeResponse
from application.use_cases.get_my_membership import GetMyMembershipUseCase
from domain.ports.identity import IdentityError

router = APIRouter(prefix="/api/v1", tags=["membership"])


def _bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="autenticación requerida")
    return authorization.split(" ", 1)[1]


@router.get("/membership/me", response_model=MembershipMeResponse)
def membership_me(
    bearer: str = Depends(_bearer_token),
    get_my_membership: GetMyMembershipUseCase = Depends(lambda: _get_my_membership),
) -> MembershipMeResponse:
    try:
        result = get_my_membership.execute(bearer)
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    m = result.membership
    if m is None:
        # ADR-012: ausencia de Membership = estado vacío tipado (200 OK).
        return MembershipMeResponse()

    return MembershipMeResponse(
        status=m.status.value,
        level=m.level.value,
        started_at=m.started_at,
        next_renewal_at=m.next_renewal_at,
        is_founder=m.is_founder,
    )


# Wiring: el router se crea con el use case inyectado por el bootstrap (api/main.py).
_get_my_membership: GetMyMembershipUseCase


def wire_router(use_case: GetMyMembershipUseCase) -> APIRouter:
    global _get_my_membership
    _get_my_membership = use_case
    return router
