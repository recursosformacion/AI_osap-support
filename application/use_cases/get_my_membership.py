"""Caso de uso: obtener el estado de Membership del usuario autenticado (ADR-008).

Flujo: IdentityResolver (JWT.sub → user_id) → MembershipRepository. Sin lógica de
negocio aquí; la ausencia de Membership es un estado válido (ADR-012) y el caso de
uso la comunica como ausencia (None), que el adaptador HTTP tipa como vacío.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.entities import Membership
from domain.ports.identity import IdentityResolver
from domain.ports.repositories import MembershipRepository


@dataclass(frozen=True)
class MyMembership:
    """Vista del estado de membership del usuario autenticado.

    `membership` es None si el usuario no tiene Membership (estado ausente, ADR-012).
    """

    user_id: str
    membership: Membership | None


class GetMyMembershipUseCase:
    def __init__(
        self,
        *,
        identity: IdentityResolver,
        memberships: MembershipRepository,
    ) -> None:
        self._identity = identity
        self._memberships = memberships

    def execute(self, bearer_token: str) -> MyMembership:
        user_id = self._identity.resolve_user_id(bearer_token)
        user_memberships = self._memberships.list_by_user(user_id)
        active = [
            m for m in user_memberships if m.status.value in ("active", "pending", "past_due")
        ]
        membership = active[0] if active else (user_memberships[0] if user_memberships else None)
        return MyMembership(user_id=user_id, membership=membership)
