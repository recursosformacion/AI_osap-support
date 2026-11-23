from __future__ import annotations

import pytest
from fastapi import HTTPException

from api.routes import admin_recognitions
from domain.ports.identity import IdentityError, IdentityPrincipal, ServiceIdentity


class _UserIdentity:
    def __init__(self, principal: IdentityPrincipal | None = None, error: Exception | None = None):
        self.principal = principal
        self.error = error

    def resolve_principal(self, bearer: str) -> IdentityPrincipal:
        if self.error is not None:
            raise self.error
        assert self.principal is not None
        return self.principal


class _ServiceAuth:
    def __init__(self, service: ServiceIdentity | None = None, error: Exception | None = None):
        self.service = service
        self.error = error
        self.required_scope: str | None = None

    def authenticate_service(self, bearer: str, *, required_scope: str) -> ServiceIdentity:
        self.required_scope = required_scope
        if self.error is not None:
            raise self.error
        assert self.service is not None
        return self.service


def test_admin_recognitions_accepts_m2m_service_with_exact_scope(monkeypatch):
    service_auth = _ServiceAuth(service=ServiceIdentity(client_id="service-123", scopes=("support:admin",)))
    monkeypatch.setattr(admin_recognitions, "_identity", _UserIdentity(error=IdentityError("not a user token")), raising=False)
    monkeypatch.setattr(admin_recognitions, "_service_auth", service_auth, raising=False)

    result = admin_recognitions._require_admin("signed-service-token")

    assert result == "service:service-123"
    assert service_auth.required_scope == "support:admin"


def test_admin_recognitions_rejects_service_without_admin_scope(monkeypatch):
    service_auth = _ServiceAuth(error=IdentityError("scope support:admin requerido"))
    monkeypatch.setattr(admin_recognitions, "_identity", _UserIdentity(error=IdentityError("not a user token")), raising=False)
    monkeypatch.setattr(admin_recognitions, "_service_auth", service_auth, raising=False)

    with pytest.raises(HTTPException) as exc:
        admin_recognitions._require_admin("signed-service-token")

    assert exc.value.status_code == 403
    assert service_auth.required_scope == "support:admin"


def test_admin_recognitions_keeps_user_role_authorization(monkeypatch):
    monkeypatch.setattr(
        admin_recognitions,
        "_identity",
        _UserIdentity(principal=IdentityPrincipal(user_id="user-1", roles=("support:admin",))),
        raising=False,
    )
    monkeypatch.setattr(admin_recognitions, "_service_auth", _ServiceAuth(), raising=False)

    assert admin_recognitions._require_admin("signed-user-token") == "user-1"


def test_admin_recognitions_does_not_fallback_when_user_lacks_role(monkeypatch):
    monkeypatch.setattr(
        admin_recognitions,
        "_identity",
        _UserIdentity(principal=IdentityPrincipal(user_id="user-1", roles=("member",))),
        raising=False,
    )
    monkeypatch.setattr(
        admin_recognitions,
        "_service_auth",
        _ServiceAuth(error=AssertionError("no debe probar el service token")),
        raising=False,
    )

    with pytest.raises(HTTPException) as exc:
        admin_recognitions._require_admin("signed-user-token")

    assert exc.value.status_code == 403
