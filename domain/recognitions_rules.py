"""Reglas puras de reconocimientos (ADR-015/016/017, Fase 3).

Principio: **las rules calculan; los use cases deciden cuándo persistir y qué evento
histórico registrar.** Estas funciones no tocan infraestructura: reciben entidades o
valores ya cargados y devuelven condiciones. La configuración de umbrales/ventanas llega
como :class:`RecognitionRules` (datos de configuración del ecosistema, ADR-016: no por
proyecto).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from domain.entities import (
    Contribution,
    ContributionType,
    Donation,
    Membership,
    MembershipStatus,
)

# Slug del proyecto canónico de los reconocimientos derivados de la relación económica
# global (SUPPORTER/FOUNDER), ADR-014/ADR-015.
ECOSYSTEM_PROJECT_SLUG = "ecosystem"

SUPPORTER_RULE_ORIGIN = "rule:supporter.active_or_donated_12m"
CONTRIBUTOR_RULE_ORIGIN = "rule:contributor.omr_evidence"
FOUNDER_ORIGIN_PREFIX = "criterion:founder"

# Tipos de evidencia que suman al acumulado de CONTRIBUTOR (configurables). Los demás
# tipos (COMMUNITY/PROMOTION/OTHER) no derivan reconocimiento automáticamente.
_DEFAULT_CONTRIBUTOR_TYPES = frozenset(
    {
        ContributionType.REVIEW,
        ContributionType.CONTENT,
        ContributionType.TRANSLATION,
        ContributionType.DEVELOPMENT,
        ContributionType.DOCUMENTATION,
    }
)


@dataclass(frozen=True)
class RecognitionRules:
    """Parámetros de las reglas (ecosistema, ADR-016; no por proyecto).

    Cerrar estos valores es decisión de configuración de negocio, no de arquitectura.
    """

    supporter_window_days: int = 365
    contributor_threshold: int = 150
    contributor_types: frozenset[ContributionType] = _DEFAULT_CONTRIBUTOR_TYPES
    founder_criterion_id: str = "founder-2026"

    def __post_init__(self) -> None:
        if self.supporter_window_days <= 0:
            raise ValueError("supporter_window_days debe ser > 0")
        if self.contributor_threshold <= 0:
            raise ValueError("contributor_threshold debe ser > 0")
        if not self.contributor_types:
            raise ValueError("contributor_types no puede ser vacío")
        if not self.founder_criterion_id or not self.founder_criterion_id.strip():
            raise ValueError("founder_criterion_id no puede ser vacío")

    @property
    def founder_origin(self) -> str:
        return founder_origin_for(self.founder_criterion_id)


def founder_origin_for(criterion_id: str) -> str:
    """Origin canónico de un reconocimiento FOUNDER (criterio congelado)."""
    return f"{FOUNDER_ORIGIN_PREFIX}.{criterion_id}"


# --- SUPPORTER (ADR-016, regla C) --------------------------------------------


def has_active_membership(memberships: Iterable[Membership]) -> bool:
    """Cierto si existe una membership en estado ACTIVE (la vigencia económica)."""
    return any(m.status is MembershipStatus.ACTIVE for m in memberships)


def has_donation_within_window(
    donations: Iterable[Donation], *, now: datetime, window_days: int
) -> bool:
    """Cierto si existe una donación completada en los últimos `window_days` días."""
    cutoff = now - timedelta(days=window_days)
    return any(d.donated_at >= cutoff for d in donations)


def supporter_condition_active(
    memberships: Iterable[Membership],
    donations: Iterable[Donation],
    *,
    now: datetime,
    rules: RecognitionRules,
) -> bool:
    """Regla C de ADR-016: membresía activa O donación en la ventana."""
    return has_active_membership(memberships) or has_donation_within_window(
        donations, now=now, window_days=rules.supporter_window_days
    )


# --- CONTRIBUTOR (ADR-017, acumulado del bucket) -----------------------------


def bucket_total(
    contributions: Iterable[Contribution], *, types: frozenset[ContributionType]
) -> int:
    """Suma de los `amount` (deltas) de los tipos del bucket.

    Sin contador físico (ADR-017): la suma se calcula desde las contribuciones
    registradas; Support nunca confía en un total acumulado enviado por el emisor.
    """
    total = 0
    for contribution in contributions:
        if contribution.contribution_type in types and contribution.amount is not None:
            total += contribution.amount
    return total


def contributor_condition_reached(
    contributions: Iterable[Contribution], *, rules: RecognitionRules
) -> tuple[bool, int]:
    """Cierto si el acumulado del bucket alcanza el umbral. Devuelve (reached, total)."""
    total = bucket_total(contributions, types=rules.contributor_types)
    return total >= rules.contributor_threshold, total
