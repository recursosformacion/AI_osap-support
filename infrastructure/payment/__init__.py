"""Adaptadores de pago de osap-support (Fase 4).

Solo infraestructura. Ningún proveedor concreto se implementa todavía (decisión
ABIERTA). `BasePaymentProvider` es la base abstracta que los futuros adaptadores
concretos (Stripe, PayPal, ...) extenderán sin tocar el dominio/aplicación.
"""

from .base import BasePaymentProvider
from .fake_payment_provider import FakePaymentProvider

__all__ = ["BasePaymentProvider", "FakePaymentProvider"]
