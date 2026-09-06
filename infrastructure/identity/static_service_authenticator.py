"""Autenticador de service tokens para desarrollo/tests (4D-1).

Resuelve un bearer token de servicio fijo a una identidad de servicio fija (client_id +
scopes). **Solo dev/test**; en production se usa `JwksServiceAuthenticator`.
"""

from __future__ import annotations

from domain.ports.identity import (
    IdentityError,
    ServiceAuthenticator,
    ServiceIdentity,
    ServiceScopeError,
)

_BEARER = "Bearer "


class StaticServiceAuthenticator(ServiceAuthenticator):
    def __init__(
        self,
        *,
        token: str,
        client_id: str,
        scopes: tuple[str, ...] = (),
    ) -> None:
        self._token = token
        self._client_id = client_id
        self._scopes = scopes

    def authenticate_service(
        self, bearer_token: str, *, required_scope: str
    ) -> ServiceIdentity:
        candidate = bearer_token
        if candidate.startswith(_BEARER):
            candidate = candidate[len(_BEARER) :]
        if candidate != self._token:
            raise IdentityError("token de servicio no válido")
        if required_scope and required_scope not in self._scopes:
            raise ServiceScopeError(f"scope requerido no presente: {required_scope}")
        return ServiceIdentity(client_id=self._client_id, scopes=self._scopes)
