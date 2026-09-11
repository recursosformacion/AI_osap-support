"""Listados admin de pagos (memberships/donations) vía TestClient.

Contrato: rol `support:admin` obligatorio (401 sin token, 403 sin rol), paginación
offset/limit con `total`, filtros por estado/nivel/periodicidad en membresías y por
usuario/rango de fechas en donaciones. Persistencia SQLAlchemy en SQLite en memoria.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.routes.admin_payments import wire_admin_payments_router
from application.use_cases.admin_list_payments import AdminListPaymentsUseCase
from domain.entities import (
    Donation,
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
    SupportMember,
)
from domain.ports.identity import IdentityError, IdentityPrincipal
from infrastructure.db.models import Base
from infrastructure.db.repositories.donation_repository import (
    SqlAlchemyDonationRepository,
)
from infrastructure.db.repositories.membership_repository import (
    SqlAlchemyMembershipRepository,
)
from infrastructure.db.repositories.payments_admin_repository import (
    SqlAlchemyPaymentsAdminRepository,
)
from infrastructure.db.repositories.support_member_repository import (
    SqlAlchemySupportMemberRepository,
)
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver

USER_A = "user-A"
USER_B = "user-B"
ADMIN = "admin-1"
NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


class _IdentityTable(StaticIdentityResolver):
    """Resolver de tests: token → (user_id, roles). Tokens fuera de la tabla → 401."""

    def __init__(self, principals: dict[str, tuple[str, tuple[str, ...]]]) -> None:
        self._principals = principals

    def resolve_principal(self, bearer_token: str) -> IdentityPrincipal:
        token = bearer_token
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if token not in self._principals:
            raise IdentityError("token no válido")
        user_id, roles = self._principals[token]
        return IdentityPrincipal(user_id=user_id, roles=roles)

    def resolve_user_id(self, bearer_token: str) -> str:
        return self.resolve_principal(bearer_token).user_id


@dataclass
class Harness:
    client: TestClient
    session: Session


@contextmanager
def _make_harness() -> Iterator[Harness]:
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = Session(engine)

    identity = _IdentityTable(
        {
            "admin-token": (ADMIN, ("user", "support:admin")),
            "non-admin-token": ("plain-user", ("user",)),
        }
    )
    payments = SqlAlchemyPaymentsAdminRepository(session)
    app = FastAPI(title="osap-support-payments-admin")
    app.include_router(
        wire_admin_payments_router(
            identity=identity,
            list_uc=AdminListPaymentsUseCase(payments=payments),
        )
    )

    yield Harness(client=TestClient(app), session=session)
    session.close()
    engine.dispose()


def _ensure_member(session: Session, user_id: str) -> None:
    repo = SqlAlchemySupportMemberRepository(session)
    if not repo.exists(user_id):
        repo.add(SupportMember(user_id=user_id))
        session.commit()


def _add_membership(
    session: Session,
    *,
    user_id: str = USER_A,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    level: MembershipLevel = MembershipLevel.SUPPORTER,
    periodicity: Periodicity = Periodicity.MONTHLY,
    amount_minor: int = 500,
    created_at: datetime = NOW,
) -> None:
    _ensure_member(session, user_id)
    repo = SqlAlchemyMembershipRepository(session)
    repo.add(
        Membership(
            id=None,
            user_id=user_id,
            status=status,
            level=level,
            periodicity=periodicity,
            amount_minor=amount_minor,
            currency="EUR",
            provider="paypal",
            customer_id=f"cust-{user_id}",
            subscription_id=f"sub-{user_id}-{status.value}-{periodicity.value}",
            email_contact="support@osap.test",
            created_at=created_at,
            updated_at=created_at,
        )
    )
    session.commit()


def _add_donation(
    session: Session,
    *,
    user_id: str = USER_A,
    amount_minor: int = 1000,
    donated_at: datetime = NOW,
) -> None:
    _ensure_member(session, user_id)
    repo = SqlAlchemyDonationRepository(session)
    repo.add(
        Donation(
            id=None,
            user_id=user_id,
            amount_minor=amount_minor,
            currency="EUR",
            provider="paypal",
            charge_id=f"charge-{user_id}-{donated_at.isoformat()}",
            email_receipt="donor@osap.test",
            donated_at=donated_at,
            created_at=donated_at,
        )
    )
    session.commit()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Auth / autorización ---------------------------------------------------------


def test_requires_admin_role() -> None:
    with _make_harness() as h:
        _add_membership(h.session)
        _add_donation(h.session)

        assert h.client.get("/api/v1/admin/payments/memberships").status_code == 401
        assert h.client.get("/api/v1/admin/payments/donations").status_code == 401

        forbidden = h.client.get(
            "/api/v1/admin/payments/memberships", headers=_auth("non-admin-token")
        )
        assert forbidden.status_code == 403

        forbidden = h.client.get(
            "/api/v1/admin/payments/donations", headers=_auth("non-admin-token")
        )
        assert forbidden.status_code == 403


# --- Memberships ----------------------------------------------------------------


def test_list_memberships_paginated_with_filters() -> None:
    with _make_harness() as h:
        _add_membership(h.session, status=MembershipStatus.ACTIVE, periodicity=Periodicity.MONTHLY)
        _add_membership(
            h.session,
            user_id=USER_B,
            status=MembershipStatus.ACTIVE,
            level=MembershipLevel.VOICE,
            periodicity=Periodicity.YEARLY,
            created_at=NOW,
        )
        _add_membership(
            h.session,
            user_id=USER_A,
            status=MembershipStatus.CANCELLED,
            level=MembershipLevel.CONTRIBUTOR,
            created_at=datetime(2026, 8, 1, tzinfo=UTC),
        )

        ok = h.client.get("/api/v1/admin/payments/memberships", headers=_auth("admin-token"))
        assert ok.status_code == 200
        body = ok.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

        active = h.client.get(
            "/api/v1/admin/payments/memberships?status=active",
            headers=_auth("admin-token"),
        )
        assert active.json()["total"] == 2

        voice = h.client.get(
            "/api/v1/admin/payments/memberships?level=voice&periodicity=yearly",
            headers=_auth("admin-token"),
        )
        assert voice.json()["total"] == 1
        assert voice.json()["items"][0]["user_id"] == USER_B

        page = h.client.get(
            "/api/v1/admin/payments/memberships?limit=2&offset=1",
            headers=_auth("admin-token"),
        )
        pbody = page.json()
        assert pbody["total"] == 3
        assert len(pbody["items"]) == 2
        statuses = {item["status"] for item in pbody["items"]}
        assert "cancelled" in statuses

        invalid = h.client.get(
            "/api/v1/admin/payments/memberships?status=unknown",
            headers=_auth("admin-token"),
        )
        assert invalid.status_code == 422


# --- Donations ------------------------------------------------------------------


def test_list_donations_paginated_with_filters() -> None:
    with _make_harness() as h:
        _add_donation(
            h.session,
            amount_minor=1000,
            donated_at=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
        )
        _add_donation(
            h.session,
            user_id=USER_B,
            amount_minor=2500,
            donated_at=datetime(2026, 9, 2, 10, 0, tzinfo=UTC),
        )
        _add_donation(
            h.session,
            amount_minor=500,
            donated_at=datetime(2026, 8, 15, 10, 0, tzinfo=UTC),
        )

        ok = h.client.get("/api/v1/admin/payments/donations", headers=_auth("admin-token"))
        assert ok.status_code == 200
        body = ok.json()
        assert body["total"] == 3

        ranged = h.client.get(
            "/api/v1/admin/payments/donations?date_from=2026-09-01T00:00:00Z&date_to=2026-09-02T23:59:59Z",
            headers=_auth("admin-token"),
        )
        rbody = ranged.json()
        assert rbody["total"] == 2
        amounts = {item["amount_minor"] for item in rbody["items"]}
        assert amounts == {1000, 2500}

        by_user = h.client.get(
            "/api/v1/admin/payments/donations?user_id=" + USER_B,
            headers=_auth("admin-token"),
        )
        assert by_user.json()["total"] == 1

        page = h.client.get(
            "/api/v1/admin/payments/donations?limit=2&offset=2",
            headers=_auth("admin-token"),
        )
        pbody = page.json()
        assert pbody["total"] == 3
        assert len(pbody["items"]) == 1
        assert pbody["items"][0]["amount_minor"] == 500
