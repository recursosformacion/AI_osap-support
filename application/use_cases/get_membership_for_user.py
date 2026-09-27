"""Caso de uso: consultar la membresía de un `user_id` concreto (M2M, fase 4.2).

A diferencia de `GetMyMembershipUseCase` (que deriva la identidad del token), aquí el
`user_id` lo aporta el llamante M2M. No hay lógica de negocio: se reutiliza la misma
selección (membership activa si la hay; si no, la más reciente o ausencia) que usa la ruta
de usuario, para que el contrato M2M sea consistente con el de la web.
"""

from __future__ import annotations

from dataclasses import dataclass

from domain.entities import Membership
from domain.ports.repositories import MembershipRepository

_ACTIVE_STATUSES = ("active", "pending", "past_due")


@dataclass(frozen=True)
class UserMembership:
    """Membresía de un usuario concreto; `membership` es None si no tiene (ADR-012)."""

    user_id: str
    membership: Membership | None


class GetMembershipForUserUseCase:
    def __init__(self, *, memberships: MembershipRepository) -> None:
        self._memberships = memberships

    def execute(self, user_id: str) -> UserMembership:
        user_memberships = self._memberships.list_by_user(user_id)
        active = [m for m in user_memberships if m.status.value in _ACTIVE_STATUSES]
        membership = active[0] if active else (user_memberships[0] if user_memberships else None)
        return UserMembership(user_id=user_id, membership=membership)
