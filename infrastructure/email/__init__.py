"""Adaptadores de email de osap-support (Fase 7)."""

from .fake_email_sender import FakeEmailSender, SentEmail

__all__ = ["FakeEmailSender", "SentEmail"]
