"""Repositorio SQLAlchemy de consultas administrativas de pagos (support:admin).

Listados paginados sobre `memberships` y `donations` para la pantalla financiera del
panel de administración. Las consultas cuentan y pagan en SQL; nunca traen la lista
completa a memoria.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from domain.entities import (
    Donation,
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
)
from domain.ports.repositories import PaymentsAdminRepository
from infrastructure.db.models import DonationModel, MembershipModel


class SqlAlchemyPaymentsAdminRepository(PaymentsAdminRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_memberships_page(
        self,
        *,
        user_id: str | None = None,
        status: MembershipStatus | None = None,
        level: MembershipLevel | None = None,
        periodicity: Periodicity | None = None,
        limit: int,
        offset: int,
    ) -> tuple[int, list[Membership]]:
        conditions = []
        if user_id is not None:
            conditions.append(MembershipModel.user_id == user_id)
        if status is not None:
            conditions.append(MembershipModel.status == status.value)
        if level is not None:
            conditions.append(MembershipModel.level == level.value)
        if periodicity is not None:
            conditions.append(MembershipModel.periodicity == periodicity.value)
        stmt = select(MembershipModel).order_by(
            MembershipModel.created_at.desc(), MembershipModel.id.desc()
        )
        if conditions:
            stmt = stmt.where(*conditions)
        total = self._count(MembershipModel, conditions)
        models = self._session.execute(
            stmt.offset(offset).limit(limit)
        ).scalars().all()
        return total, [self._to_membership(m) for m in models]

    def list_donations_page(
        self,
        *,
        user_id: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int,
        offset: int,
    ) -> tuple[int, list[Donation]]:
        conditions = []
        if user_id is not None:
            conditions.append(DonationModel.user_id == user_id)
        if date_from is not None:
            conditions.append(DonationModel.donated_at >= date_from)
        if date_to is not None:
            conditions.append(DonationModel.donated_at <= date_to)
        stmt = select(DonationModel).order_by(
            DonationModel.donated_at.desc(), DonationModel.id.desc()
        )
        if conditions:
            stmt = stmt.where(*conditions)
        total = self._count(DonationModel, conditions)
        models = self._session.execute(
            stmt.offset(offset).limit(limit)
        ).scalars().all()
        return total, [self._to_donation(m) for m in models]

    def _count(self, model, conditions: list) -> int:
        stmt = select(func.count()).select_from(model)
        if conditions:
            stmt = stmt.where(*conditions)
        return int(self._session.execute(stmt).scalar_one())

    def _to_membership(self, model: MembershipModel) -> Membership:
        return Membership(
            id=model.id,
            user_id=model.user_id,
            status=MembershipStatus(model.status),
            level=MembershipLevel(model.level),
            periodicity=Periodicity(model.periodicity),
            amount_minor=model.amount_minor,
            currency=model.currency,
            provider=model.provider,
            customer_id=model.customer_id,
            subscription_id=model.subscription_id,
            started_at=model.started_at,
            renewed_at=model.renewed_at,
            next_renewal_at=model.next_renewal_at,
            cancelled_at=model.cancelled_at,
            expires_at=model.expires_at,
            email_contact=model.email_contact,
            is_founder=model.is_founder,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    def _to_donation(self, model: DonationModel) -> Donation:
        return Donation(
            id=model.id,
            user_id=model.user_id,
            amount_minor=model.amount_minor,
            currency=model.currency,
            provider=model.provider,
            charge_id=model.charge_id,
            receipt_id=model.receipt_id,
            email_receipt=model.email_receipt,
            donated_at=model.donated_at,
            created_at=model.created_at,
        )
