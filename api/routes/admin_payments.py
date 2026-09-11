"""Rutas administrativas de pagos (rol support:admin).

Listados paginados de membresías y donaciones para la pantalla financiera del panel de
administración. Frontera: el principal del token debe portar el rol `support:admin`;
sin él → 403. El router es un adaptador fino: toda la lógica vive en el use case.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from api.schemas.payments import (
    AdminDonationItem,
    AdminDonationsPage,
    AdminMembershipItem,
    AdminMembershipsPage,
)
from application.use_cases.admin_list_payments import AdminListPaymentsUseCase
from domain.entities import MembershipLevel, MembershipStatus, Periodicity
from domain.ports.identity import IdentityError, IdentityResolver

router = APIRouter(prefix="/api/v1/admin", tags=["admin-payments"])

_ADMIN_ROLE = "support:admin"

_DEFAULT_LIMIT = 20
_MAX_LIMIT = 200


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


def _parse_status(raw: str | None) -> MembershipStatus | None:
    if raw is None:
        return None
    try:
        return MembershipStatus(raw.strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"estado desconocido: {raw}") from None


def _parse_level(raw: str | None) -> MembershipLevel | None:
    if raw is None:
        return None
    try:
        return MembershipLevel(raw.strip().lower())
    except ValueError:
        raise HTTPException(status_code=422, detail=f"nivel desconocido: {raw}") from None


def _parse_periodicity(raw: str | None) -> Periodicity | None:
    if raw is None:
        return None
    try:
        return Periodicity(raw.strip().lower())
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"periodicidad desconocida: {raw}"
        ) from None


def _to_membership_item(membership) -> AdminMembershipItem:
    return AdminMembershipItem(
        id=membership.id if membership.id is not None else -1,
        user_id=membership.user_id,
        status=membership.status.value,
        level=membership.level.value,
        periodicity=membership.periodicity.value,
        amount_minor=membership.amount_minor,
        currency=membership.currency,
        provider=membership.provider,
        subscription_id=membership.subscription_id,
        started_at=membership.started_at,
        renewed_at=membership.renewed_at,
        next_renewal_at=membership.next_renewal_at,
        cancelled_at=membership.cancelled_at,
        expires_at=membership.expires_at,
        email_contact=membership.email_contact,
        is_founder=membership.is_founder,
        created_at=membership.created_at,
        updated_at=membership.updated_at,
    )


def _to_donation_item(donation) -> AdminDonationItem:
    return AdminDonationItem(
        id=donation.id if donation.id is not None else -1,
        user_id=donation.user_id,
        amount_minor=donation.amount_minor,
        currency=donation.currency,
        provider=donation.provider,
        charge_id=donation.charge_id,
        receipt_id=donation.receipt_id,
        email_receipt=donation.email_receipt,
        donated_at=donation.donated_at,
        created_at=donation.created_at,
    )


@router.get("/payments/memberships", response_model=AdminMembershipsPage)
def admin_list_memberships(
    user_id: str | None = Query(default=None, min_length=1),
    status: str | None = Query(default=None),
    level: str | None = Query(default=None),
    periodicity: str | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    bearer: str = Depends(_bearer_token),
) -> AdminMembershipsPage:
    _require_admin(bearer)
    total, rows = _list_uc.list_memberships(
        user_id=user_id,
        status=_parse_status(status),
        level=_parse_level(level),
        periodicity=_parse_periodicity(periodicity),
        limit=limit,
        offset=offset,
    )
    return AdminMembershipsPage(
        total=total, items=[_to_membership_item(m) for m in rows]
    )


@router.get("/payments/donations", response_model=AdminDonationsPage)
def admin_list_donations(
    user_id: str | None = Query(default=None, min_length=1),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_LIMIT, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    bearer: str = Depends(_bearer_token),
) -> AdminDonationsPage:
    _require_admin(bearer)
    total, rows = _list_uc.list_donations(
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return AdminDonationsPage(total=total, items=[_to_donation_item(d) for d in rows])


# Wiring: bootstrap (api/main.py) inyecta identity y el use case de listado.
_identity: IdentityResolver
_list_uc: AdminListPaymentsUseCase


def wire_admin_payments_router(
    *,
    identity: IdentityResolver,
    list_uc: AdminListPaymentsUseCase,
) -> APIRouter:
    global _identity, _list_uc
    _identity = identity
    _list_uc = list_uc
    return router
