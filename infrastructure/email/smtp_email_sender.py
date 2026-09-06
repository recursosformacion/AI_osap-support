"""Enviador de email real por SMTP (infraestructura).

No registra en logs ni marca como enviado: llama al servidor SMTP configurado y solo
devuelve True si el mensaje fue aceptado. En fallo controlado lanza
:class:`EmailSendError` (el worker lo convierte en reintento con backoff).
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage as _EmailMessage

from domain.ports.email import EmailMessage, EmailSender


class EmailSendError(RuntimeError):
    """El proveedor SMTP rechazó/no pudo aceptar el mensaje."""


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    from_address: str = "support@openmusicrepository.com"
    use_tls: bool = True
    timeout_seconds: float = 15.0


class SmtpEmailSender(EmailSender):
    """Envía mensajes por SMTP (STARTTLS o SSL según `use_tls`).

    - Sin credenciales: requiere host/from_address; `username` vacío = envío anónimo
      (el servidor decide). En producción la configuración debe venir de variables
      `OSAP_SUPPORT_SMTP_*` (ver api.main._email_for).
    - Las plantillas se resuelven por `template`; si no existe, se rechaza el envío
      (error explícito, nunca un correo vacío presentado como enviado).
    """

    def __init__(self, settings: SmtpSettings, templates: dict[str, str] | None = None) -> None:
        if not settings.host or not settings.from_address:
            raise EmailSendError("SMTP host/from_address no configurados")
        self._settings = settings
        self._templates = templates or {}

    def send(self, message: EmailMessage) -> bool:
        if message.template not in self._templates:
            raise EmailSendError(f"plantilla no definida: {message.template}")
        body = self._templates[message.template]
        subject = _subject_for(message.template, body)

        email = _EmailMessage()
        email["From"] = self._settings.from_address
        email["To"] = message.recipient_email
        email["Subject"] = subject
        email.set_content(body)

        try:
            if self._settings.use_tls:
                with smtplib.SMTP(
                    self._settings.host,
                    self._settings.port,
                    timeout=self._settings.timeout_seconds,
                ) as smtp:
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                    if self._settings.username:
                        smtp.login(self._settings.username, self._settings.password)
                    smtp.send_message(email)
            else:
                with smtplib.SMTP(
                    self._settings.host,
                    self._settings.port,
                    timeout=self._settings.timeout_seconds,
                ) as smtp:
                    smtp.ehlo()
                    if self._settings.username:
                        smtp.login(self._settings.username, self._settings.password)
                    smtp.send_message(email)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailSendError(f"SMTP no aceptó el mensaje: {exc}") from exc
        return True


def _subject_for(template: str, body: str) -> str:
    first = next((line.strip() for line in body.splitlines() if line.strip()), "")
    return f"{template}: {first[:80]}" if first else template


DEFAULT_TEMPLATES: dict[str, str] = {
    "membership_confirmation": (
        "Gracias por apoyar OSAP con una membresía.\n"
        "Tu relación de apoyo está activa. Puedes ver su estado en la página de soporte."
    ),
    "renewal_notice": (
        "Tu membresía de OSAP se ha renovado correctamente. "
        "Gracias por seguir apoyando el proyecto."
    ),
    "payment_failed": (
        "No hemos podido procesar el pago de tu membresía. Revisa tu método de pago en tu cuenta."
    ),
    "membership_cancelled": "Tu membresía de OSAP ha sido cancelada.",
    "membership_expired": "Tu membresía de OSAP ha expirado.",
    "donation_confirmation": (
        "Gracias por tu donación a OSAP. Tu apoyo hace posible el proyecto."
    ),
}
