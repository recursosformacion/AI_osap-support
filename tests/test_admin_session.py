from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api import admin_session
from api.routes.admin_web import wire_admin_web_router

_SECRET = "test-support-session-secret-with-enough-length-123456"


class _ServiceAuth:
    def __init__(self) -> None:
        self.called = False

    def authenticate_service(self, token: str, *, required_scope: str) -> SimpleNamespace:
        self.called = True
        return SimpleNamespace(client_id="osap-api", scopes=("support:admin",))


def _client(signer: admin_session.AdminSessionSigner) -> TestClient:
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        server=SimpleNamespace(admin_handoff_origins=["https://app.openmusicrepository.com"])
    )
    app.include_router(
        wire_admin_web_router(
            service_authenticator=_ServiceAuth(),
            admin_session_signer=signer,
        )
    )
    return TestClient(app, base_url="https://support.openmusicrepository.com")


def test_signer_roundtrip_and_rejects_service_tokens() -> None:
    signer = admin_session.AdminSessionSigner(_SECRET, 3600)
    token, ttl = signer.issue(client_id="osap-api")
    assert ttl == 3600
    claims = signer.validate(token)
    assert claims is not None
    assert claims["scope"] == "support:admin"
    now = int(time.time())
    service_token = jwt.encode(
        {"token_use": "service", "scope": "support:admin", "iat": now, "exp": now + 300},
        _SECRET,
        algorithm="HS256",
    )
    assert signer.validate(service_token) is None


def test_handoff_issues_local_session_instead_of_service_token() -> None:
    signer = admin_session.AdminSessionSigner(_SECRET, 28800)
    token = jwt.encode(
        {"exp": int(time.time()) + 180, "client_id": "osap-api"},
        key="",
        algorithm="none",
    )
    response = _client(signer).post(
        "/api/v1/admin/web/session",
        headers={"Origin": "https://app.openmusicrepository.com"},
        data={"token": token, "next": "./recognitions"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie_header = response.headers["set-cookie"]
    assert "max-age=28800" in cookie_header.lower()
    cookie_value = cookie_header.split("osap_support_admin=", 1)[1].split(";", 1)[0]
    assert cookie_value != token
    assert signer.validate(cookie_value) is not None


def test_admin_page_and_api_accept_local_session() -> None:
    signer = admin_session.AdminSessionSigner(_SECRET, 3600)
    client = _client(signer)
    local, _ = signer.issue()
    client.cookies.set("osap_support_admin", local, path="/")
    assert client.get("/api/v1/admin/web/recognitions").status_code == 200

    from api.routes.admin_recognitions import _require_admin

    admin_session.set_signer(signer)
    assert _require_admin(local) == "service:support-admin-web"
    admin_session.set_signer(None)


def test_expired_local_session_is_not_accepted() -> None:
    signer = admin_session.AdminSessionSigner(_SECRET, 3600)
    now = int(time.time())
    expired = jwt.encode(
        {
            "sub": "support-admin-web",
            "scope": "support:admin",
            "token_use": admin_session.SESSION_USE,
            "iat": now - 120,
            "exp": now - 60,
        },
        _SECRET,
        algorithm="HS256",
    )
    assert signer.validate(expired) is None
    assert signer.is_session_token(expired) is True
