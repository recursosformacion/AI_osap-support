"""Entrega interna de comunicaciones redactadas por OSAP (boletín de noticias).

No envía SMTP directamente: crea un `CommunicationEvent` pendiente y el worker existente
lo entrega. Autenticación de servicio con `X-OSAP-Internal-Token`.
"""

from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from domain.entities import CommunicationEvent, CommunicationEventStatus
from infrastructure.db.models import CommunicationEventModel
from infrastructure.db.repositories.communication_event_repository import (
    SqlAlchemyCommunicationEventRepository,
)
from infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

router = APIRouter()


class NewsDigestBody(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    recipient_email: str = Field(min_length=3, max_length=255)
    subject: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=100_000)
    html: str | None = Field(default=None, max_length=200_000)
    dedupe_key: str = Field(min_length=1, max_length=160)
    template: str = Field(default="news_digest", max_length=64)


def _require_token(token: str | None) -> None:
    expected = os.environ.get("OSAP_INTERNAL_SERVICE_TOKEN", "").strip()
    if not expected or not token or not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=403, detail="token interno inválido")


@router.post("/internal/communications/news", status_code=201)
def queue_news_digest(
    body: NewsDigestBody,
    request: Request,
    x_osap_internal_token: str | None = Header(default=None),
) -> dict[str, object]:
    _require_token(x_osap_internal_token)
    session: Session = request.app.state.db_session
    existing = session.execute(
        select(CommunicationEventModel).where(
            CommunicationEventModel.dedupe_key == body.dedupe_key
        )
    ).scalar_one_or_none()
    if existing is not None:
        return {"id": existing.id, "status": "duplicate"}

    event = CommunicationEvent(
        id=None,
        user_id=body.user_id,
        template=body.template,
        recipient_email=body.recipient_email,
        status=CommunicationEventStatus.PENDING,
        subject=body.subject,
        body=body.text,
        body_html=body.html,
        dedupe_key=body.dedupe_key,
    )
    repository = SqlAlchemyCommunicationEventRepository(session)
    repository.add(event)
    SqlAlchemyUnitOfWork(session).commit()
    return {"id": event.id, "status": "queued"}


def wire_internal_communications_router(app: FastAPI) -> None:
    app.include_router(router)

