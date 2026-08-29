"""Repositorio SQLAlchemy de Donation (mapeo persistencia <-> dominio)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entities import Donation
from domain.ports.repositories import DonationRepository
from infrastructure.db.models import DonationModel


class SqlAlchemyDonationRepository(DonationRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, donation: Donation) -> Donation:
        model = self._to_model(donation)
        self._session.add(model)
        self._session.flush()
        donation.id = model.id
        return donation

    def get_by_charge(self, provider: str, charge_id: str) -> Donation | None:
        model = self._session.execute(
            select(DonationModel).where(
                DonationModel.provider == provider,
                DonationModel.charge_id == charge_id,
            )
        ).scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    def list_by_user(self, user_id: str) -> list[Donation]:
        models = self._session.execute(
            select(DonationModel).where(DonationModel.user_id == user_id)
        ).scalars().all()
        return [self._to_domain(m) for m in models]

    def _to_model(self, d: Donation) -> DonationModel:
        return DonationModel(
            id=d.id,
            user_id=d.user_id,
            amount_minor=d.amount_minor,
            currency=d.currency,
            provider=d.provider,
            charge_id=d.charge_id,
            receipt_id=d.receipt_id,
            email_receipt=d.email_receipt,
            donated_at=d.donated_at,
            created_at=d.created_at,
        )

    def _to_domain(self, model: DonationModel) -> Donation:
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
