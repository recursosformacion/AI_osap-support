"""Tests del contrato M2M de membresía (fase 4.2).

Cubren: autenticación/autorización M2M (401 sin token, 403 sin scope o client fuera de la
allowlist), membresía activa (active/tier/valid_from/valid_until/source), membresía caducada
o no activa, y ausencia de membresía (200 + vacío tipado).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.main import create_app
from api.routes.m2m_membership import wire_m2m_membership_router
from application.use_cases.get_membership_for_user import GetMembershipForUserUseCase
from domain.entities import (
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
    SupportMember,
)
from infrastructure.config import M2mClientConfig, Settings
from infrastructure.db.models import Base
from infrastructure.db.repositories.membership_repository import SqlAlchemyMembershipRepository
from infrastructure.db.repositories.support_member_repository import (
    SqlAlchemySupportMemberRepository,
)
from infrastructure.identity.static_service_authenticator import StaticServiceAuthenticator

TOKEN = "Bearer service-token"
USER = "uuid-m2m-1"


def _settings() -> Settings:
    s = Settings(env="test")
    s.server.dev_token = "dev-token"
    s.server.dev_user_id = USER
    return s


def _membership(
    *,
    status: MembershipStatus = MembershipStatus.ACTIVE,
    expires_at: datetime | None = None,
) -> Membership:
    return Membership(
        id=None,
        user_id=USER,
        status=status,
        level=MembershipLevel.VOICE,
        periodicity=Periodicity.MONTHLY,
        amount_minor=1000,
        currency="EUR",
        provider="stripe",
        customer_id="cus_1",
        subscription_id="sub_1",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=expires_at,
        next_renewal_at=datetime(2026, 2, 1, tzinfo=UTC),
    )


def _client(
    *,
    memberships: tuple[Membership, ...] = (),
    scopes: tuple[str, ...] = ("api:read",),
    allowlisted: bool = True,
) -> TestClient:
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    session = Session(engine)
    SqlAlchemySupportMemberRepository(session).add(SupportMember(user_id=USER))
    repo = SqlAlchemyMembershipRepository(session)
    for m in memberships:
        repo.add(m)
    session.commit()

    app = create_app(_settings())
    # Sobrescribe el wiring real (el router usa globals) con dependencias de test.
    wire_m2m_membership_router(
        service_authenticator=StaticServiceAuthenticator(
            token="service-token", client_id="omr-dev", scopes=scopes
        ),
        m2m_scope=lambda client_id: (
            M2mClientConfig(client_id="omr-dev", source="dev") if allowlisted else None
        ),
        membership_uc=GetMembershipForUserUseCase(
            memberships=SqlAlchemyMembershipRepository(session)
        ),
    )
    return TestClient(app)


@pytest.fixture
def client_active() -> TestClient:
    return _client(memberships=(_membership(),))


def test_requires_bearer(client_active: TestClient) -> None:
    assert client_active.get(f"/api/v1/m2m/membership?user_id={USER}").status_code == 401


def test_invalid_token_401(client_active: TestClient) -> None:
    resp = client_active.get(
        f"/api/v1/m2m/membership?user_id={USER}", headers={"Authorization": "Bearer wrong"}
    )
    assert resp.status_code == 401


def test_missing_scope_403() -> None:
    client = _client(memberships=(_membership(),), scopes=("support:ingest",))
    resp = client.get(
        f"/api/v1/m2m/membership?user_id={USER}", headers={"Authorization": TOKEN}
    )
    assert resp.status_code == 403


def test_client_not_allowlisted_403() -> None:
    client = _client(memberships=(_membership(),), allowlisted=False)
    resp = client.get(
        f"/api/v1/m2m/membership?user_id={USER}", headers={"Authorization": TOKEN}
    )
    assert resp.status_code == 403


def test_active_membership(client_active: TestClient) -> None:
    resp = client_active.get(
        f"/api/v1/m2m/membership?user_id={USER}", headers={"Authorization": TOKEN}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["active"] is True
    assert body["tier"] == "donor"
    assert body["source"] == "stripe"
    assert body["valid_from"] is not None
    assert body["valid_until"] is not None


def test_expired_membership_is_not_active() -> None:
    past = datetime(2020, 1, 1, tzinfo=UTC)
    client = _client(memberships=(_membership(expires_at=past),))
    body = client.get(
        f"/api/v1/m2m/membership?user_id={USER}", headers={"Authorization": TOKEN}
    ).json()
    assert body["active"] is False
    assert body["tier"] is None


def test_cancelled_membership_is_not_active() -> None:
    client = _client(memberships=(_membership(status=MembershipStatus.CANCELLED),))
    body = client.get(
        f"/api/v1/m2m/membership?user_id={USER}", headers={"Authorization": TOKEN}
    ).json()
    assert body["active"] is False
    assert body["tier"] is None


def test_without_membership_returns_empty_typed() -> None:
    client = _client()
    resp = client.get(
        f"/api/v1/m2m/membership?user_id={USER}", headers={"Authorization": TOKEN}
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "active": False,
        "tier": None,
        "valid_from": None,
        "valid_until": None,
        "source": None,
    }


def test_missing_user_id_422(client_active: TestClient) -> None:
    assert client_active.get(
        "/api/v1/m2m/membership", headers={"Authorization": TOKEN}
    ).status_code == 422
