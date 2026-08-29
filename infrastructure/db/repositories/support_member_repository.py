"""Repositorio SQLAlchemy de SupportMember (mapeo persistencia <-> dominio)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entities import SupportMember
from domain.ports.repositories import SupportMemberRepository
from infrastructure.db.models import SupportMemberModel


class SqlAlchemySupportMemberRepository(SupportMemberRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, member: SupportMember) -> SupportMember:
        existing = self.get(member.user_id)
        if existing is not None:
            return existing  # idempotente: la relación ya existe
        model = SupportMemberModel(
            user_id=member.user_id,
            created_at=member.created_at,
            data_version=member.data_version,
        )
        self._session.add(model)
        self._session.flush()
        return member

    def get(self, user_id: str) -> SupportMember | None:
        model = self._session.execute(
            select(SupportMemberModel).where(SupportMemberModel.user_id == user_id)
        ).scalar_one_or_none()
        if model is None:
            return None
        return SupportMember(
            user_id=model.user_id,
            created_at=model.created_at,
            data_version=model.data_version,
        )

    def exists(self, user_id: str) -> bool:
        return self.get(user_id) is not None
