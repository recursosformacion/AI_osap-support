"""Aplicación FastAPI de OSAP Support.

Conexión FastAPI → caso de uso → ports → infraestructura (Fase 5).
La identidad se deriva del token (ADR-008/ADR-002). JWKS productivo queda ABIERTO;
en dev/test se usa StaticIdentityResolver.
"""

from __future__ import annotations

from fastapi import FastAPI

from api.routes.membership import wire_router
from api.routes.webhooks import wire_webhook_router
from application.use_cases.get_my_membership import GetMyMembershipUseCase
from application.use_cases.process_payment_webhook import ProcessPaymentWebhookUseCase
from infrastructure.config import Settings, load_settings
from infrastructure.db.repositories.communication_event_repository import (
    SqlAlchemyCommunicationEventRepository,
)
from infrastructure.db.repositories.donation_repository import SqlAlchemyDonationRepository
from infrastructure.db.repositories.membership_repository import SqlAlchemyMembershipRepository
from infrastructure.db.repositories.payment_event_repository import SqlAlchemyPaymentEventRepository
from infrastructure.db.session import make_session_factory
from infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.identity.static_identity_resolver import StaticIdentityResolver
from infrastructure.payment.fake_payment_provider import FakePaymentProvider


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title=settings.server.app_title, version=settings.server.app_version)
    app.state.settings = settings

    @app.get("/")
    def health() -> dict[str, str]:
        return {"service": "osap-support", "version": settings.server.app_version, "status": "ok"}

    # Wiring (Fase 5/6): FastAPI → use case → ports → infraestructura.
    # JWKS productivo queda abierto (ABIERTA); resolver estático y provider fake solo dev/test.
    session = make_session_factory()()
    identity = StaticIdentityResolver(
        token=settings.server.dev_token,
        user_id=settings.server.dev_user_id,
    )
    membership_use_case = GetMyMembershipUseCase(
        identity=identity,
        memberships=SqlAlchemyMembershipRepository(session),
    )
    app.include_router(wire_router(membership_use_case))

    webhook_use_case = ProcessPaymentWebhookUseCase(
        provider=FakePaymentProvider(),
        payment_events=SqlAlchemyPaymentEventRepository(session),
        memberships=SqlAlchemyMembershipRepository(session),
        donations=SqlAlchemyDonationRepository(session),
        communications=SqlAlchemyCommunicationEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
    app.include_router(wire_webhook_router(webhook_use_case))

    return app


def create_app_from_settings(settings: Settings | None = None) -> FastAPI:
    return create_app(settings or load_settings())


def run() -> None:
    import uvicorn

    settings = load_settings()
    uvicorn.run(
        "api.main:create_app_from_settings",
        factory=True,
        host=settings.server.host,
        port=settings.server.port,
    )
