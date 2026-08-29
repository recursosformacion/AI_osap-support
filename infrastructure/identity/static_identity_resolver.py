"""Resolver de identidad para desarrollo/tests (ADR-002).

Resuelve un bearer token fijo a un `user_id` fijo. **Solo dev/test**, análogo al
`StaticTokenAuthenticator` de osap-api. La verificación real contra el JWKS de Auth
queda como decisión abierta de infraestructura (no se implementa en esta fase).
"""

from __future__ import annotations

from domain.ports.identity import IdentityError, IdentityResolver

_BEARER = "Bearer "


class StaticIdentityResolver(IdentityResolver):
    def __init__(self, *, token: str, user_id: str) -> None:
        self._token = token
        self._user_id = user_id

    def resolve_user_id(self, bearer_token: str) -> str:
        candidate = bearer_token
        if candidate.startswith(_BEARER):
            candidate = candidate[len(_BEARER) :]
        if candidate != self._token:
            raise IdentityError("token no válido")
        return self._user_id
