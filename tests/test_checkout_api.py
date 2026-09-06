"""Tests de las rutas HTTP de checkout (donación y membresía).

Cubren: 401 sin token, 401 token inválido, validación DTO (amount<=0, nivel/periodicidad
no soportados, currency no ISO), respuesta 200 con URL real del proveedor, y que en
membership el `plan_id` nunca llega del navegador (solo level+periodicity).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from api.routes import checkout as checkout_module
from infrastructure.config import Settings

TOKEN = "Bearer dev-token"
USER = "uuid-1234"


def _settings() -> Settings:
    s = Settings(env="test")
    s.server.dev_token = "dev-token"
    s.server.dev_user_id = USER
    return s


@pytest.fixture
def client() -> Iterator[TestClient]:
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from infrastructure.db.models import Base

    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    yield TestClient(create_app(_settings()))
    engine.dispose()


def test_checkout_donation_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/donation",
        json={"amount_minor": 500, "currency": "EUR", "return_url": "/return"},
    )
    assert resp.status_code == 401


def test_checkout_donation_invalid_token(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/donation",
        headers={"Authorization": "Bearer wrong"},
        json={"amount_minor": 500, "currency": "EUR", "return_url": "/return"},
    )
    assert resp.status_code == 401


def test_checkout_donation_invalid_amount(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/donation",
        headers={"Authorization": TOKEN},
        json={"amount_minor": 0, "currency": "EUR", "return_url": "/return"},
    )
    assert resp.status_code == 422


def test_checkout_donation_invalid_currency(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/donation",
        headers={"Authorization": TOKEN},
        json={"amount_minor": 500, "currency": "eur", "return_url": "/return"},
    )
    assert resp.status_code == 422


def test_checkout_donation_returns_real_checkout_url(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/donation",
        headers={"Authorization": TOKEN},
        json={"amount_minor": 500, "currency": "EUR", "return_url": "/return"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "donation"
    assert body["checkout_url"].startswith("https://")
    assert body["provider_session_id"]


def test_checkout_membership_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/membership",
        json={"level": "supporter", "periodicity": "monthly", "return_url": "/return"},
    )
    assert resp.status_code == 401


def test_checkout_membership_unsupported_level(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/membership",
        headers={"Authorization": TOKEN},
        json={"level": "diamond", "periodicity": "monthly", "return_url": "/return"},
    )
    assert resp.status_code == 422


def test_checkout_membership_unsupported_periodicity(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/membership",
        headers={"Authorization": TOKEN},
        json={"level": "supporter", "periodicity": "weekly", "return_url": "/return"},
    )
    assert resp.status_code == 422


def test_checkout_membership_plan_id_not_accepted_from_client(client: TestClient) -> None:
    # El navegador NO puede elegir plan_id: el contrato no lo acepta (422 por extra).
    resp = client.post(
        "/api/v1/checkouts/membership",
        headers={"Authorization": TOKEN},
        json={
            "level": "supporter",
            "periodicity": "monthly",
            "return_url": "/return",
            "plan_id": "P-HACKED",
        },
    )
    assert resp.status_code == 422


def test_checkout_membership_returns_real_checkout_url(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/checkouts/membership",
        headers={"Authorization": TOKEN},
        json={"level": "voice", "periodicity": "yearly", "return_url": "/return"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "membership"
    assert body["checkout_url"].startswith("https://")
    assert body["checkout_url"].endswith("/voice/yearly")
    assert body["provider_session_id"]


def test_checkout_routes_have_no_sql_or_provider_logic() -> None:
    import inspect

    module_source = inspect.getsource(checkout_module)
    # Solo código ejecutable (sin el docstring del módulo): el adaptador delega en el
    # caso de uso y no contiene SQL/ORM ni SDK de proveedores concretos.
    source = module_source.split('"""', 2)[2]
    # `session` como palabra (no `provider_session_id`/`CheckoutSession`, que son parte
    # del contrato) y sin SQL/ORM ni SDK de proveedores concretos.
    for banned in (
        "sqlalchemy",
        "from sqlalchemy",
        "Session(",
        "select(",
        "import stripe",
        "import paypal",
        "\.execute\(",
    ):
        assert banned not in source
    import re

    assert not re.search(r"\bsession\b", source)
