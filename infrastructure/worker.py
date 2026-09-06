"""Proceso worker de OSAP Support.

Consume la cola de CommunicationEvents pendientes (ADR-006): lee los eventos
pendientes/vencidos, los envía con el EmailSender real y persiste estado
(sent/failed + backoff). Es UN proceso separado y arrancable; no vive dentro de
uvicorn. Ejecución:

    python -m infrastructure.worker            # bucle infinito (producción)
    python -m infrastructure.worker --once     # una pasada (tests/cron)

Env: OSAP_SUPPORT_EMAIL_SENDER=fake|smtp (fake SOLO dev/test; en production el
arranque falla si no hay SMTP real configurado).
"""

from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

from application.use_cases.process_communication_events import (
    ProcessCommunicationEventsUseCase,
    WorkerSummary,
)
from domain.ports.email import EmailSender
from infrastructure.config import Settings, load_settings
from infrastructure.db.repositories.communication_event_repository import (
    SqlAlchemyCommunicationEventRepository,
)
from infrastructure.db.session import make_session_factory
from infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from infrastructure.email.fake_email_sender import FakeEmailSender
from infrastructure.email.smtp_email_sender import DEFAULT_TEMPLATES, SmtpEmailSender

logger = logging.getLogger("osap-support.worker")

_NON_PRODUCTION = {"development", "test", "dev", "testing"}

_POLL_SECONDS = float(os.environ.get("OSAP_SUPPORT_WORKER_POLL_SECONDS", "30"))


class EmailProviderMissing(RuntimeError):
    """No hay proveedor de email real configurado (fail-fast en production)."""


def build_email_sender(settings: Settings) -> EmailSender:
    mode = os.environ.get("OSAP_SUPPORT_EMAIL_SENDER", "").strip().lower()
    if settings.server.env in _NON_PRODUCTION:
        if mode == "smtp":
            return _smtp_sender(settings)
        return FakeEmailSender()
    # production: SOLO SMTP real configurado.
    if mode != "smtp":
        raise EmailProviderMissing(
            "OSAP_SUPPORT_EMAIL_SENDER=smtp required in production "
            "(plus OSAP_SUPPORT_SMTP_* / sección [smtp] de osap.toml)"
        )
    return _smtp_sender(settings)


def _smtp_sender(settings: Settings) -> SmtpEmailSender:
    from infrastructure.email.smtp_email_sender import SmtpSettings

    smtp = settings.smtp
    return SmtpEmailSender(
        SmtpSettings(
            host=smtp.host,
            port=smtp.port,
            username=smtp.username,
            password=smtp.password,
            from_address=smtp.from_address,
            use_tls=smtp.tls,
        ),
        templates=DEFAULT_TEMPLATES,
    )


@dataclass(frozen=True)
class WorkerRunner:
    """Loop ejecutable: una pasada o bucle infinito con señal de parada."""

    process: Callable[[], WorkerSummary]
    poll_seconds: float = _POLL_SECONDS

    def run_once(self) -> WorkerSummary:
        return self.process()

    def run_forever(self, stop_event: Callable[[], bool] | None = None) -> None:
        while True:
            if stop_event is not None and stop_event():
                logger.info("worker: parada solicitada")
                return
            try:
                summary = self.process()
                if summary.sent or summary.failed:
                    logger.info(
                        "worker: processed=%d sent=%d failed=%d",
                        summary.processed,
                        summary.sent,
                        summary.failed,
                    )
            except Exception:  # noqa: BLE001
                logger.exception("worker: error en pasada; se reintenta")
            time.sleep(self.poll_seconds)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="osap-support-worker")
    parser.add_argument("--once", action="store_true", help="una sola pasada y salir")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO)

    settings = load_settings()
    email_sender = build_email_sender(settings)
    session_factory = make_session_factory()
    session = session_factory()
    use_case = ProcessCommunicationEventsUseCase(
        communications=SqlAlchemyCommunicationEventRepository(session),
        email_sender=email_sender,
        uow=SqlAlchemyUnitOfWork(session),
    )
    runner = WorkerRunner(process=lambda: use_case.execute(limit=args.limit))
    try:
        if args.once:
            summary = runner.run_once()
            print(f"processed={summary.processed} sent={summary.sent} failed={summary.failed}")
        else:
            runner.run_forever()
    finally:
        session.close()


if __name__ == "__main__":
    main()
