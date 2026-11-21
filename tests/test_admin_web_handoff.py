from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.routes.admin_web import wire_admin_web_router


class _ServiceAuth:
    def authenticate_service(self, token: str, *, required_scope: str):
        assert token.count(".") == 2
        assert required_scope == "support:admin"
        return SimpleNamespace(client_id="osap-api", scopes=("support:admin",))


def _client() -> tuple[TestClient, str]:
    token = jwt.encode({"exp": int(time.time()) + 180}, key="", algorithm="none")
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        server=SimpleNamespace(admin_handoff_origins=["https://app.openmusicrepository.com"])
    )
    app.include_router(wire_admin_web_router(service_authenticator=_ServiceAuth()))
    return TestClient(app, base_url="https://support.openmusicrepository.com"), token


def test_support_handoff_sets_http_only_scoped_cookie_and_redirects():
    client, token = _client()
    response = client.post(
        "/api/v1/admin/web/session",
        headers={"Origin": "https://app.openmusicrepository.com"},
        data={"token": token, "next": "./recognitions"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "./recognitions"
    cookie = response.headers["set-cookie"].lower()
    assert "osap_support_admin=" in cookie
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "max-age=179" in cookie or "max-age=180" in cookie


def test_support_admin_page_uses_cookie_and_rejects_url_token():
    client, token = _client()
    assert client.get("/api/v1/admin/web/recognitions").status_code == 401
    client.cookies.set("osap_support_admin", token, secure=True, path="/api/v1/admin")
    assert client.get("/api/v1/admin/web/recognitions").status_code == 200
    assert client.get("/api/v1/admin/web/recognitions", params={"token": token}).status_code == 400


def test_support_handoff_rejects_untrusted_origin_and_external_redirect():
    client, token = _client()
    bad_origin = client.post(
        "/api/v1/admin/web/session",
        headers={"Origin": "https://attacker.example"},
        data={"token": token},
        follow_redirects=False,
    )
    assert bad_origin.status_code == 403
    bad_next = client.post(
        "/api/v1/admin/web/session",
        headers={"Origin": "https://app.openmusicrepository.com"},
        data={"token": token, "next": "https://attacker.example"},
        follow_redirects=False,
    )
    assert bad_next.status_code == 400
