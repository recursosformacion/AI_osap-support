"""Repositorio SQLAlchemy de Membership (mapeo persistencia <-> dominio)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entities import (
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
)
from domain.ports.repositories import MembershipRepository
from infrastructure.db.models import MembershipModel


class SqlAlchemyMembershipRepository(MembershipRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, membership: Membership) -> Membership:
        model = self._to_model(membership)
        self._session.add(model)
        self._session.flush()
        membership.id = model.id
        return membership

    def get_by_subscription(self, provider: str, subscription_id: str) -> Membership | None:
        model = self._session.execute(
            select(MembershipModel).where(
                MembershipModel.provider == provider,
                MembershipModel.subscription_id == subscription_id,
            )
        ).scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    def list_by_user(self, user_id: str) -> list[Membership]:
        models = self._session.execute(
            select(MembershipModel).where(MembershipModel.user_id == user_id)
        ).scalars().all()
        return [self._to_domain(m) for m in models]

    def _to_model(self, m: Membership) -> MembershipModel:
        return MembershipModel(
            id=m.id,
            user_id=m.user_id,
            status=m.status.value,
            level=m.level.value,
            periodicity=m.periodicity.value,
            amount_minor=m.amount_minor,
            currency=m.currency,
            provider=m.provider,
            customer_id=m.customer_id,
            subscription_id=m.subscription_id,
            started_at=m.started_at,
            renewed_at=m.renewed_at,
            next_renewal_at=m.next_renewal_at,
            cancelled_at=m.cancelled_at,
            expires_at=m.expires_at,
            email_contact=m.email_contact,
            is_founder=m.is_founder,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )

    def _to_domain(self, model: MembershipModel) -> Membership:
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
