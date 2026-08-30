"""Tests de la API de usuario (Fase 5): GET /api/v1/membership/me.

Cubren: identidad del token (ADR-008/ADR-002), membership existente, ausencia de
membership (ADR-012: 200 + vacío tipado), seguridad (401 sin token, identidad inválida,
sin acceso arbitrario por URL), y que la ruta es solo adaptador (sin SQL).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.main import create_app
from application.use_cases.get_my_membership import GetMyMembershipUseCase
from domain.entities import (
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
    SupportMember,
)
from infrastructure.config import Settings
from infrastructure.db.models import Base
from infrastructure.db.repositories.membership_repository import SqlAlchemyMembershipRepository
from infrastructure.db.repositories.support_member_repository import (
    SqlAlchemySupportMemberRepository,
)
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver

TOKEN = "Bearer dev-token"
USER = "uuid-1234"


def _settings() -> Settings:
    s = Settings(env="test")
    s.server.dev_token = "dev-token"
    s.server.dev_user_id = USER
    return s


def _membership() -> Membership:
    return Membership(
        id=None,
        user_id=USER,
        status=MembershipStatus.ACTIVE,
        level=MembershipLevel.VOICE,
        periodicity=Periodicity.MONTHLY,
        amount_minor=1000,
        currency="EUR",
        provider="stripe",
        customer_id="cus_1",
        subscription_id="sub_1",
    )


def _build_client(*, with_membership: bool) -> Iterator[TestClient]:
    # SQLite en memoria compartida entre threads (TestClient usa otro hilo).
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        member_repo = SqlAlchemySupportMemberRepository(session)
        member_repo.add(SupportMember(user_id=USER))
        if with_membership:
            SqlAlchemyMembershipRepository(session).add(_membership())
        session.commit()

        identity = StaticIdentityResolver(token="dev-token", user_id=USER)
        use_case = GetMyMembershipUseCase(
            identity=identity,
            memberships=SqlAlchemyMembershipRepository(session),
        )
        from api.routes.membership import wire_router

        app = create_app(_settings())
        app.include_router(wire_router(use_case))
        yield TestClient(app)
    engine.dispose()


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    """App sin membership para el usuario autenticado."""
    yield from _build_client(with_membership=False)


@pytest.fixture
def api_client_with_membership() -> Iterator[TestClient]:
    """App con una membership activa para el usuario autenticado."""
    yield from _build_client(with_membership=True)


def test_membership_me_requires_auth(api_client: TestClient) -> None:
    assert api_client.get("/api/v1/membership/me").status_code == 401


def test_membership_me_with_invalid_identity_returns_401(api_client: TestClient) -> None:
    resp = api_client.get("/api/v1/membership/me", headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_membership_me_with_membership(api_client_with_membership: TestClient) -> None:
    resp = api_client_with_membership.get(
        "/api/v1/membership/me", headers={"Authorization": TOKEN}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["level"] == "voice"
    assert body["is_founder"] is False


def test_membership_me_without_membership_returns_200_empty_typed(api_client: TestClient) -> None:
    # ADR-012: ausencia = 200 + estado vacío tipado (no 404, no null completo).
    resp = api_client.get("/api/v1/membership/me", headers={"Authorization": TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": None,
        "level": None,
        "started_at": None,
        "next_renewal_at": None,
        "is_founder": False,
    }


def test_membership_me_does_not_accept_user_id_from_url(api_client: TestClient) -> None:
    # ADR-008/V-014: no existe /membership/{id} ni /membership/{user_id}.
    resp = api_client.get(f"/api/v1/membership/{USER}", headers={"Authorization": TOKEN})
    assert resp.status_code == 404
    assert resp.json().get("detail") is not None


def test_membership_me_route_has_no_sql() -> None:
    # La ruta es adaptador: no contiene SQL/ORM (se verifica leyendo el módulo).
    import inspect

    from api.routes import membership as membership_module

    source = inspect.getsource(membership_module)
    assert "sqlalchemy" not in source
    assert "Session" not in source
    assert "session" not in source
    assert "select(" not in source
    assert ".execute(" not in source.replace("get_my_membership.execute", "")
