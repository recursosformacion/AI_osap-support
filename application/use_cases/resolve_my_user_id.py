"""Caso de uso: resolver la identidad de la sesión (ADR-002).

El único uso que puede materializarse en esta fase sin BD de negocio ni proveedores es
la resolución de `user_id` (JWT.sub) a partir del token. Los casos de uso de membresía
(dependientes de ADR-004/005/007/008) se añadirán en fases posteriores.
"""

from __future__ import annotations

from domain.ports.identity import IdentityResolver


class ResolveMyUserIdUseCase:
    """Devuelve el `user_id` (= Auth.user_id = JWT.sub) de la sesión actual."""

    def __init__(self, identity: IdentityResolver) -> None:
        self._identity = identity

    def execute(self, bearer_token: str) -> str:
        return self._identity.resolve_user_id(bearer_token)
