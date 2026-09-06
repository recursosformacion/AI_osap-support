"""Resolver de identidad para desarrollo/tests (ADR-002, 4D-1).

Resuelve un bearer token fijo a un principal (user_id + roles) fijo. **Solo dev/test**,
análogo al `StaticTokenAuthenticator` de osap-api. Permite representar usuarios con roles
(p. ej. `support:admin`) sin JWKS.
"""

from __future__ import annotations

from domain.ports.identity import IdentityError, IdentityPrincipal, IdentityResolver

_BEARER = "Bearer "


class StaticIdentityResolver(IdentityResolver):
    def __init__(
        self, *, token: str, user_id: str, roles: tuple[str, ...] = ()
    ) -> None:
        self._token = token
        self._user_id = user_id
        self._roles = roles

    def resolve_principal(self, bearer_token: str) -> IdentityPrincipal:
        candidate = bearer_token
        if candidate.startswith(_BEARER):
            candidate = candidate[len(_BEARER) :]
        if candidate != self._token:
            raise IdentityError("token no válido")
        return IdentityPrincipal(user_id=self._user_id, roles=self._roles)

    def resolve_user_id(self, bearer_token: str) -> str:
        return self.resolve_principal(bearer_token).user_id
