"""Caso de uso: listados administrativos de pagos (support:admin).

Consulta paginada de `memberships` y `donations` para la pantalla financiera del panel.
Es una consulta de gestión; la lógica de negocio no decide importes ni estados, solo
traslada filtros y paginación al repositorio.
"""

from __future__ import annotations

from datetime import datetime

from domain.entities import Donation, Membership, MembershipLevel, MembershipStatus, Periodicity
from domain.ports.repositories import PaymentsAdminRepository


class AdminListPaymentsUseCase:
    def __init__(self, *, payments: PaymentsAdminRepository) -> None:
        self._payments = payments

    def list_memberships(
        self,
        *,
        user_id: str | None = None,
        status: MembershipStatus | None = None,
        level: MembershipLevel | None = None,
        periodicity: Periodicity | None = None,
        limit: int,
        offset: int,
    ) -> tuple[int, list[Membership]]:
        return self._payments.list_memberships_page(
            user_id=user_id,
            status=status,
            level=level,
            periodicity=periodicity,
            limit=limit,
            offset=offset,
        )

    def list_donations(
        self,
        *,
        user_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int,
        offset: int,
    ) -> tuple[int, list[Donation]]:
        return self._payments.list_donations_page(
            user_id=user_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
