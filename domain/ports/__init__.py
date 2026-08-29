"""Puertos del dominio de OSAP Support.

Contratos estables (SOURCE OF TRUTH): identidad (ADR-002), pagos (ADR-005) y email
(ADR-006). No implementan lógica ni proveedores; solo declaran la frontera.
"""

from .email import EmailMessage, EmailSender
from .identity import IdentityError, IdentityProviderProtocol, IdentityResolver
from .payment import CheckoutSession, PaymentProvider, PaymentReference

__all__ = [
    "CheckoutSession",
    "EmailMessage",
    "EmailSender",
    "IdentityError",
    "IdentityProviderProtocol",
    "IdentityResolver",
    "PaymentProvider",
    "PaymentReference",
]
