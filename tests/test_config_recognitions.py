"""Tests de wiring de configuración 4D-2: `[recognitions]` y `[m2m]`.

Verifican el adaptador `[recognitions]` → RecognitionRules (domain) y la allowlist M2M
(client_id → source + proyectos) con la convención env > toml > defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.entities import ContributionType
from infrastructure.config import (
    Settings,
    m2m_scope_for_settings,
    recognition_rules_from_settings,
)

_DEFAULT_TYPES = frozenset(
    {
        ContributionType.REVIEW,
        ContributionType.CONTENT,
        ContributionType.TRANSLATION,
        ContributionType.DEVELOPMENT,
        ContributionType.DOCUMENTATION,
    }
)


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_recognitions_defaults_when_toml_has_no_section(tmp_path: Path) -> None:
    toml = _write_toml(tmp_path / "osap.toml", "")
    settings = Settings(env="test", toml_file=toml)
    rules = recognition_rules_from_settings(settings)
    assert rules.supporter_window_days == 365
    assert rules.contributor_threshold == 150
    assert rules.contributor_types == _DEFAULT_TYPES
    assert rules.founder_criterion_id == "founder-2026"


def test_recognitions_reads_toml_section(tmp_path: Path) -> None:
    toml = _write_toml(
        tmp_path / "osap.toml",
        "\n".join(
            [
                "[recognitions]",
                "supporter_window_days = 180",
                "contributor_threshold = 200",
                'contributor_types = ["review", "translation"]',
                'founder_criterion_id = "founder-v2"',
            ]
        ),
    )
    settings = Settings(env="test", toml_file=toml)
    rules = recognition_rules_from_settings(settings)
    assert rules.supporter_window_days == 180
    assert rules.contributor_threshold == 200
    assert rules.contributor_types == frozenset(
        {ContributionType.REVIEW, ContributionType.TRANSLATION}
    )
    assert rules.founder_criterion_id == "founder-v2"
    assert rules.founder_origin == "criterion:founder.founder-v2"


def test_recognitions_rejects_unknown_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in (
        "OSAP_SUPPORT_RECOGNITIONS_SUPPORTER_WINDOW_DAYS",
        "OSAP_SUPPORT_RECOGNITIONS_CONTRIBUTOR_THRESHOLD",
        "OSAP_SUPPORT_RECOGNITIONS_CONTRIBUTOR_TYPES",
        "OSAP_SUPPORT_RECOGNITIONS_FOUNDER_CRITERION_ID",
    ):
        monkeypatch.delenv(env_var, raising=False)
    toml = _write_toml(
        tmp_path / "osap.toml",
        "\n".join(["[recognitions]", 'contributor_types = ["review", "no-existe"]']),
    )
    settings = Settings(env="test", toml_file=toml)
    with pytest.raises(ValueError):
        recognition_rules_from_settings(settings)


def test_recognitions_env_overrides_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OSAP_SUPPORT_RECOGNITIONS_CONTRIBUTOR_THRESHOLD", "999")
    monkeypatch.setenv("OSAP_SUPPORT_RECOGNITIONS_CONTRIBUTOR_TYPES", "review,development")
    toml = _write_toml(
        tmp_path / "osap.toml",
        "\n".join(["[recognitions]", "contributor_threshold = 200"]),
    )
    settings = Settings(env="test", toml_file=toml)
    rules = recognition_rules_from_settings(settings)
    assert rules.contributor_threshold == 999
    assert rules.contributor_types == frozenset(
        {ContributionType.REVIEW, ContributionType.DEVELOPMENT}
    )


def test_m2m_allowlist_parsed_and_scoped(tmp_path: Path) -> None:
    toml = _write_toml(
        tmp_path / "osap.toml",
        "\n".join(
            [
                "[m2m]",
                'clients = [ { client_id = "omr-backend", source = "omr", projects = ["omr"] } ]',
            ]
        ),
    )
    settings = Settings(env="test", toml_file=toml)
    scope = m2m_scope_for_settings(settings, "omr-backend")
    assert scope is not None
    assert scope.source == "omr"
    assert scope.projects == ["omr"]
    assert m2m_scope_for_settings(settings, "otro-client") is None
