"""Rutas de checkout (donación y membresía).

Adaptador HTTP fino: autenticación → validación DTO → use case → resultado real del
proveedor. No contiene lógica de negocio ni SQL. El `plan_id` NUNCA llega del
navegador: el backend lo resuelve desde `level`+`periodicity` (configuración interna).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from application.use_cases.checkout_donation import CheckoutDonationUseCase
from application.use_cases.checkout_membership import CheckoutMembershipUseCase
from domain.entities import MembershipLevel, Periodicity
from domain.ports.identity import IdentityError, IdentityResolver
from domain.ports.payment import CheckoutSession

router = APIRouter(prefix="/api/v1", tags=["checkout"])

_SUPPORTED_LEVELS = {level.value for level in MembershipLevel}
_SUPPORTED_PERIODICITIES = {periodicity.value for periodicity in Periodicity}


def _bearer_token(authorization: str | None = Header(default=None)) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="autenticación requerida")
    return authorization.split(" ", 1)[1]


class DonationCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: int = Field(..., ge=1)
    currency: str = Field(..., min_length=3, max_length=3)
    return_url: str = Field(..., min_length=1)

    @field_validator("currency")
    @classmethod
    def _iso_currency(cls, value: str) -> str:
        if not value.isalpha() or not value.isupper():
            raise ValueError("currency debe ser ISO 4217 en mayúsculas")
        return value


class MembershipCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str
    periodicity: str
    return_url: str = Field(..., min_length=1)

    @field_validator("level")
    @classmethod
    def _supported_level(cls, value: str) -> str:
        if value not in _SUPPORTED_LEVELS:
            raise ValueError(f"nivel no soportado: {value}")
        return value

    @field_validator("periodicity")
    @classmethod
    def _supported_periodicity(cls, value: str) -> str:
        if value not in _SUPPORTED_PERIODICITIES:
            raise ValueError(f"periodicidad no soportada: {value}")
        return value


class CheckoutResponse(BaseModel):
    checkout_url: str
    provider_session_id: str
    mode: str
    return_url: str


def _current_user_id(bearer: str) -> str:
    """Resuelve `user_id` desde el token (JWT.sub). Nunca llega del navegador."""
    try:
        return _identity.resolve_user_id(bearer)
    except IdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _provider_error(exc: Exception) -> HTTPException:
    # El proveedor falla (credenciales, plan no configurado, PayPal rechaza la petición):
    # error explícito 502; nunca se inventa una URL de pago.
    return HTTPException(status_code=502, detail=f"proveedor de pago: {exc}")


@router.post("/checkouts/donation", response_model=CheckoutResponse)
def checkout_donation(
    body: DonationCheckoutRequest,
    bearer: str = Depends(_bearer_token),
) -> CheckoutResponse:
    user_id = _current_user_id(bearer)
    try:
        checkout = _donation_uc.execute(
            user_id=user_id,
            amount_minor=body.amount_minor,
            currency=body.currency,
            return_url=body.return_url,
        )
    except Exception as exc:
        raise _provider_error(exc) from exc
    return _to_response(checkout)


@router.post("/checkouts/membership", response_model=CheckoutResponse)
def checkout_membership(
    body: MembershipCheckoutRequest,
    bearer: str = Depends(_bearer_token),
) -> CheckoutResponse:
    user_id = _current_user_id(bearer)
    try:
        checkout = _membership_uc.execute(
            user_id=user_id,
            level=body.level,
            periodicity=body.periodicity,
            return_url=body.return_url,
        )
    except Exception as exc:
        raise _provider_error(exc) from exc
    return _to_response(checkout)


def _to_response(checkout: CheckoutSession) -> CheckoutResponse:
    return CheckoutResponse(
        checkout_url=checkout.checkout_url,
        provider_session_id=checkout.provider_session_id,
        mode=checkout.mode.value,
        return_url=checkout.return_url,
    )


# Wiring: el bootstrap (api/main.py) inyecta resolver y casos de uso reales.
_identity: IdentityResolver
_donation_uc: CheckoutDonationUseCase
_membership_uc: CheckoutMembershipUseCase


def wire_checkout_router(
    identity: IdentityResolver,
    donation_uc: CheckoutDonationUseCase,
    membership_uc: CheckoutMembershipUseCase,
) -> APIRouter:
    global _identity, _donation_uc, _membership_uc
    _identity = identity
    _donation_uc = donation_uc
    _membership_uc = membership_uc
    return router
