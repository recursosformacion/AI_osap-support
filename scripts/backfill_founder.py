"""Backfill de reconocimientos FOUNDER (históricos) desde memberships.is_founder.

Materializa el criterio congelado de fundador (ADR-015, origin `criterion:founder.<id>`)
como reconocimientos HISTORICAL/ACTIVE permanentes en `projects` canónico `ecosystem`.
Idempotente: si ya existe el reconocimiento (user_id, ecosystem, founder) se omite; nunca
duplica. `granted_at` = MIN(started_at) de las membresías founder del usuario.

Uso: python scripts/backfill_founder.py [--dry-run] [--criterion-id founder-2026]
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402
from infrastructure.db.models import (  # noqa: E402
    MembershipModel,
    ProjectModel,
    RecognitionEventModel,
    RecognitionModel,
)
from infrastructure.db.session import make_session_factory  # noqa: E402


def _founder_member_ids(session: Session) -> list[str]:
    rows = session.execute(
        select(MembershipModel.user_id)
        .where(MembershipModel.is_founder.is_(True))
        .distinct()
    ).scalars().all()
    return list(rows)


def _earliest_founder_date(session: Session, user_id: str) -> datetime:
    rows = session.execute(
        select(MembershipModel.started_at, MembershipModel.created_at).where(
            MembershipModel.user_id == user_id,
            MembershipModel.is_founder.is_(True),
        )
    ).all()
    candidates = [d for d, _ in rows if d is not None]
    if not candidates:
        candidates = [created for _, created in rows if created is not None]
    return min(candidates) if candidates else datetime.now(UTC).replace(tzinfo=None)


def _project_id(session: Session, slug: str) -> int:
    value = session.execute(
        select(ProjectModel.id).where(ProjectModel.slug == slug)
    ).scalar_one_or_none()
    if value is None:
        raise RuntimeError(f"proyecto {slug} no existe (¿migración 0002 aplicada?)")
    return value


def _exists(session: Session, user_id: str, project_id: int) -> bool:
    row = session.execute(
        select(RecognitionModel.id).where(
            RecognitionModel.user_id == user_id,
            RecognitionModel.project_id == project_id,
            RecognitionModel.type == "founder",
        )
    ).scalar_one_or_none()
    return row is not None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validar sin escribir")
    parser.add_argument("--criterion-id", default="founder-2026")
    args = parser.parse_args()

    settings = load_settings()
    factory = make_session_factory()
    session: Session = factory()
    created = 0
    skipped = 0
    try:
        ecosystem_id = _project_id(session, "ecosystem")
        for user_id in _founder_member_ids(session):
            if _exists(session, user_id, ecosystem_id):
                skipped += 1
                continue
            granted_at = _earliest_founder_date(session, user_id)
            origin = f"criterion:founder.{args.criterion_id}"
            if args.dry_run:
                print(f"[dry-run] founder para {user_id} (origin={origin})")
                created += 1
                continue
            recognition = RecognitionModel(
                user_id=user_id,
                project_id=ecosystem_id,
                type="founder",
                kind="historical",
                status="active",
                granted_at=granted_at,
                origin=origin,
                reason=f"fundador OSAP — criterio congelado {args.criterion_id}",
                created_at=granted_at,
                updated_at=granted_at,
            )
            session.add(recognition)
            session.flush()
            session.add(
                RecognitionEventModel(
                    user_id=user_id,
                    project_id=ecosystem_id,
                    type="founder",
                    event_type="activated",
                    status_after="active",
                    origin=origin,
                    occurred_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            created += 1
        session.commit()
    finally:
        session.close()

    print(f"founder backfill: created={created} skipped={skipped}")


if __name__ == "__main__":
    main()
