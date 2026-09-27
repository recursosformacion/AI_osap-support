"""Ruta M2M de consulta de membresía (fase 4.2, ADR-017).

`osap-support` es la **fuente de verdad** del estado donor de un usuario. Esta ruta permite
a `osap-api` consultar la membresía de un `user_id` **sin interpretar pagos**: solo lee y
traduce el resultado al contrato del funnel.

Contrato:
  GET /api/v1/m2m/membership?user_id=<id>
  → { "active": bool, "tier": "donor"|null, "valid_from":…, "valid_until":…, "source":… }

Autorización (mismo mecanismo M2M que las contribuciones): service token válido con el
scope requerido (por defecto `api:read`, configurable con
`OSAP_SUPPORT_M2M_MEMBERSHIP_SCOPE`) y client_id presente en la allowlist `[m2m]`.

Sin lógica de negocio ni SQL aquí: delega en `GetMembershipForUserUseCase`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC

from fastapi import APIRouter, Depends, Header, HTTPException

from api.schemas.membership import MembershipM2mResponse
from application.use_cases.get_membership_for_user import GetMembershipForUserUseCase
from domain.entities import MembershipStatus, utc_now
from domain.ports.identity import (
    IdentityError,
    ServiceAuthenticator,
    ServiceScopeError,
)
from infrastructure.config import M2mClientConfig

router = APIRouter(prefix="/api/v1/m2m", tags=["m2m-membership"])

# Un scope de LECTURA existente (no se añaden scopes ni se toca auth). Configurable para
# poder apuntar a un scope dedicado en el futuro sin cambiar código.
_REQUIRED_SCOPE = os.environ.get("OSAP_SUPPORT_M2M_MEMBERSHIP_SCOPE", "api:read")


def _bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="autenticación requerida")
    return authorization.split(" ", 1)[1]


@router.get("/membership", response_model=MembershipM2mResponse)
def membership(user_id: str, bearer: str = Depends(_bearer_token)) -> MembershipM2mResponse:
    try:
        service = _service_authenticator.authenticate_service(
            bearer, required_scope=_REQUIRED_SCOPE
        )
    except ServiceScopeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if _m2m_scope(service.client_id) is None:
        raise HTTPException(status_code=403, detail="client M2M no permitido")

    result = _membership_uc.execute(user_id)
    m = result.membership
    if m is None:
        # Estado ausente tipado (200 OK), igual que `membership/me` (ADR-012).
        return MembershipM2mResponse()

    # `active`: membresía realmente vigente (no past_due/cancelled/expired ni caducada).
    # `expires_at` puede venir sin tzinfo desde la BD: se normaliza a UTC antes de comparar.
    expires = m.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    active = m.status is MembershipStatus.ACTIVE and (expires is None or expires > utc_now())
    return MembershipM2mResponse(
        active=active,
        # 4.2: un único nivel de funnel. Cualquier membresía activa materializa `donor`.
        tier="donor" if active else None,
        valid_from=m.started_at,
        valid_until=m.expires_at or m.next_renewal_at,
        source=m.provider,
    )


# Wiring inyectado por el bootstrap (api/main.py).
_service_authenticator: ServiceAuthenticator
_m2m_scope: Callable[[str], M2mClientConfig | None]
_membership_uc: GetMembershipForUserUseCase


def wire_m2m_membership_router(
    *,
    service_authenticator: ServiceAuthenticator,
    m2m_scope: Callable[[str], M2mClientConfig | None],
    membership_uc: GetMembershipForUserUseCase,
) -> APIRouter:
    global _service_authenticator, _m2m_scope, _membership_uc
    _service_authenticator = service_authenticator
    _m2m_scope = m2m_scope
    _membership_uc = membership_uc
    return router
