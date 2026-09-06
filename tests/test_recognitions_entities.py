"""Tests de entidades y reglas de reconocimientos (ADR-015/016/017).

Cubren invariantes de las entidades (concesión manual vs derivada, consentimiento,
FOUNDER como sello histórico permanentemente vigente, deltas de contribución) y las reglas
puras: SUPPORTER (regla C) y CONTRIBUTOR (acumulado del bucket).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from domain.entities import (
    Contribution,
    ContributionType,
    Donation,
    Membership,
    MembershipLevel,
    MembershipStatus,
    Periodicity,
    Recognition,
    RecognitionKind,
    RecognitionStatus,
    RecognitionType,
)
from domain.recognitions_rules import (
    ECOSYSTEM_PROJECT_SLUG,
    RecognitionRules,
    bucket_total,
    contributor_condition_reached,
    founder_origin_for,
    has_active_membership,
    has_donation_within_window,
    supporter_condition_active,
)

NOW = datetime(2026, 9, 6, 12, 0, 0, tzinfo=UTC)


def _membership(status: MembershipStatus = MembershipStatus.ACTIVE) -> Membership:
    return Membership(
        id=None,
        user_id="u-1",
        status=status,
        level=MembershipLevel.SUPPORTER,
        periodicity=Periodicity.MONTHLY,
        amount_minor=1000,
        currency="EUR",
        provider="paypal",
        customer_id="cus",
        subscription_id="sub",
        started_at=NOW,
    )


def _donation(days_ago: int) -> Donation:
    return Donation(
        id=None,
        user_id="u-1",
        amount_minor=1000,
        currency="EUR",
        provider="paypal",
        charge_id=f"ch-{days_ago}",
        donated_at=NOW - timedelta(days=days_ago),
    )


def _contribution(
    ctype: ContributionType, amount: int, summary: str = "evidencia"
) -> Contribution:
    return Contribution(
        id=None,
        user_id="u-1",
        project_slug="omr",
        contribution_type=ctype,
        summary=summary,
        amount=amount,
        source="omr",
        source_reference=f"{ctype.value}/{summary}/{amount}",
    )


def _rules(**overrides: object) -> RecognitionRules:
    return RecognitionRules(**overrides)  # type: ignore[arg-type]


# --- invariantes de Recognition -------------------------------------------------


def test_granted_requires_granted_by() -> None:
    with pytest.raises(ValueError):
        Recognition(
            id=None,
            user_id="u-1",
            project_slug="omr",
            recognition_type=RecognitionType.VOICE,
            kind=RecognitionKind.GRANTED,
            status=RecognitionStatus.ACTIVE,
            granted_at=NOW,
            granted_by=None,
        )


def test_derived_and_historical_forbid_granted_by() -> None:
    for kind in (RecognitionKind.DERIVED, RecognitionKind.HISTORICAL):
        with pytest.raises(ValueError):
            Recognition(
                id=None,
                user_id="u-1",
                project_slug=ECOSYSTEM_PROJECT_SLUG,
                recognition_type=RecognitionType.SUPPORTER,
                kind=kind,
                status=RecognitionStatus.ACTIVE,
                granted_at=NOW,
                granted_by="admin-1",
                origin="rule:test",
            )


def test_public_and_public_revoked_are_incompatible() -> None:
    with pytest.raises(ValueError):
        Recognition(
            id=None,
            user_id="u-1",
            project_slug="omr",
            recognition_type=RecognitionType.VOICE,
            kind=RecognitionKind.GRANTED,
            status=RecognitionStatus.ACTIVE,
            granted_at=NOW,
            granted_by="admin-1",
            public=True,
            public_revoked_at=NOW,
        )


def test_inactive_with_consent_is_not_publicly_visible() -> None:
    # ADR-016: consentimiento previo NO hace visible un reconocimiento no vigente.
    recognition = Recognition(
        id=None,
        user_id="u-1",
        project_slug=ECOSYSTEM_PROJECT_SLUG,
        recognition_type=RecognitionType.SUPPORTER,
        kind=RecognitionKind.DERIVED,
        status=RecognitionStatus.INACTIVE,
        granted_at=NOW,
        origin="rule:supporter",
        public=True,
        public_since=NOW,
    )
    assert recognition.status is RecognitionStatus.INACTIVE
    assert recognition.public
    assert not recognition.is_publicly_visible


def test_founder_is_historical_seal_permanently_active() -> None:
    # ADR-015: FOUNDER (kind=HISTORICAL) permanece permanentemente vigente (status
    # ACTIVE, active_until=None). "Histórico" = origen por criterio, no inactividad.
    recognition = Recognition(
        id=None,
        user_id="u-1",
        project_slug=ECOSYSTEM_PROJECT_SLUG,
        recognition_type=RecognitionType.FOUNDER,
        kind=RecognitionKind.HISTORICAL,
        status=RecognitionStatus.ACTIVE,
        granted_at=NOW,
        origin=founder_origin_for("founder-2026"),
        active_until=None,
    )
    assert recognition.status is RecognitionStatus.ACTIVE
    assert recognition.active_until is None
    assert not recognition.public  # sin consentimiento no es visible


def test_contribution_requires_positive_delta_or_none() -> None:
    with pytest.raises(ValueError):
        _contribution(ContributionType.REVIEW, amount=-1)
    ok = _contribution(ContributionType.REVIEW, amount=0)
    assert ok.amount == 0
    without_amount = Contribution(
        id=None,
        user_id="u-1",
        project_slug="omr",
        contribution_type=ContributionType.REVIEW,
        summary="evidencia",
        amount=None,
        source="omr",
        source_reference="ref-1",
    )
    assert without_amount.amount is None
    assert without_amount.idempotency_key == ("omr", "ref-1")


# --- SUPPORTER: regla C (ADR-016) ----------------------------------------------


def test_supporter_active_membership_or_recent_donation() -> None:
    rules = _rules(supporter_window_days=365)
    assert has_active_membership([_membership(MembershipStatus.ACTIVE)])
    assert not has_active_membership([_membership(MembershipStatus.CANCELLED)])

    assert has_donation_within_window([_donation(10)], now=NOW, window_days=365)
    assert not has_donation_within_window([_donation(400)], now=NOW, window_days=365)

    # C: membership activa O donación en ventana.
    assert supporter_condition_active(
        [], [_donation(10)], now=NOW, rules=rules
    )
    assert supporter_condition_active(
        [_membership(MembershipStatus.ACTIVE)], [], now=NOW, rules=rules
    )
    assert not supporter_condition_active(
        [_membership(MembershipStatus.CANCELLED)], [_donation(400)], now=NOW, rules=rules
    )


def test_supporter_rule_is_ecosystem_wide_not_per_project() -> None:
    # La ventana es parámetro de ecosistema (ADR-016): la regla no recibe project_slug.
    rules = _rules(supporter_window_days=30)
    assert supporter_condition_active(
        [], [_donation(10)], now=NOW, rules=rules
    )
    assert not supporter_condition_active(
        [], [_donation(60)], now=NOW, rules=rules
    )


# --- CONTRIBUTOR: acumulado del bucket (ADR-017) --------------------------------


def test_bucket_sums_only_configured_types_and_deltas() -> None:
    rules = _rules()
    contributions = [
        _contribution(ContributionType.REVIEW, 40),
        _contribution(ContributionType.REVIEW, 60),
        _contribution(ContributionType.DOCUMENTATION, 50),
        _contribution(ContributionType.COMMUNITY, 1000),  # no deriva (fuera del bucket)
    ]
    assert bucket_total(contributions, types=rules.contributor_types) == 150


def test_contributor_threshold_default_150() -> None:
    rules = _rules()
    contributions = [
        _contribution(ContributionType.REVIEW, 100),
        _contribution(ContributionType.TRANSLATION, 49),
    ]
    reached, total = contributor_condition_reached(contributions, rules=rules)
    assert (reached, total) == (False, 149)

    contributions.append(_contribution(ContributionType.CONTENT, 1))
    reached, total = contributor_condition_reached(contributions, rules=rules)
    assert (reached, total) == (True, 150)


def test_rules_validation_and_founder_origin() -> None:
    with pytest.raises(ValueError):
        _rules(supporter_window_days=0)
    with pytest.raises(ValueError):
        _rules(contributor_threshold=-1)
    rules = _rules(founder_criterion_id="founder-2026")
    assert rules.founder_origin == "criterion:founder.founder-2026"
    assert founder_origin_for("v2") == "criterion:founder.v2"
