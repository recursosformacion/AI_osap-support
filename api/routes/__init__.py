"""Rutas de la API de OSAP Support."""

from .membership import router as membership_router
from .membership import wire_router as wire_membership_router
from .webhooks import router as webhook_router
from .webhooks import wire_webhook_router

__all__ = [
    "membership_router",
    "webhook_router",
    "wire_membership_router",
    "wire_webhook_router",
]
