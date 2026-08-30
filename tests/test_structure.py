"""Tests de estructura y aislamiento (Fase 1).

- Las unidades importables existen.
- El dominio (ports) no depende de infraestructura (frontera limpia ADR-001).
- No se han creado tablas de negocio ni endpoints de negocio en esta fase.
"""

from __future__ import annotations

from domain import ports


def test_ports_are_importable() -> None:
    assert callable(ports.IdentityResolver.resolve_user_id)
    assert callable(ports.PaymentProvider.create_checkout)
    assert callable(ports.PaymentProvider.resolve_customer)
    assert callable(ports.PaymentProvider.get_subscription)
    assert callable(ports.PaymentProvider.parse_webhook)
    assert callable(ports.EmailSender.send)


def test_domain_does_not_depend_on_infrastructure() -> None:
    # Los ports no deben importar desde infrastructure (dependencia invertida).
    from domain.ports import email, identity, payment

    for mod in (email, identity, payment):
        source = __import__(mod.__name__, fromlist=["*"]).__file__ or ""
        assert "infrastructure" not in source.replace("\\", "/")
