"""Tests de migración Alembic 0002 (reconocimientos y contribuciones).

Verifica contra una BD SQLite temporal aislada (solo tests; producción usa MariaDB
`osap_support`, ADR-003):
- upgrade crea projects/recognitions/recognition_events/contributions con sus UNIQUE;
- seed de `projects` (canónico `ecosystem` + `omr`);
- downgrade revierte (incluida la 0001).
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

NEW_TABLES = {
    "projects",
    "recognitions",
    "recognition_events",
    "contributions",
}

ALL_SUPPORT_TABLES = {
    "support_members",
    "memberships",
    "donations",
    "payment_events",
    "communication_events",
} | NEW_TABLES


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", "infrastructure/db/alembic")
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    cfg.set_main_option("prepend_sys_path", ".")
    return cfg


def test_upgrade_creates_recognition_tables_and_seeds_projects() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        url = f"sqlite:///{tmp_path.as_posix()}"
        cfg = _alembic_config(url)

        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert NEW_TABLES <= tables

            rq = inspect(engine).get_unique_constraints("recognitions")
            assert any(
                set(c["column_names"]) == {"user_id", "project_id", "type"}
                for c in rq
            )
            cq = inspect(engine).get_unique_constraints("contributions")
            assert any(
                set(c["column_names"]) == {"source", "source_reference"} for c in cq
            )

            with engine.connect() as conn:
                slugs = {
                    row[0]
                    for row in conn.execute(text("SELECT slug FROM projects")).fetchall()
                }
            assert slugs == {"ecosystem", "omr"}
        finally:
            engine.dispose()

        command.downgrade(cfg, "base")
        engine = create_engine(url)
        try:
            tables_after = set(inspect(engine).get_table_names())
            assert ALL_SUPPORT_TABLES.isdisjoint(tables_after)
        finally:
            engine.dispose()
    finally:
        time.sleep(0.2)
        tmp_path.unlink(missing_ok=True)


def test_downgrade_0002_head_to_0001_keeps_original_tables() -> None:
    """El downgrade propio de 0002 (head → 0001) solo elimina SUS tablas.

    Distingue la responsabilidad de 0002 (projects/recognitions/recognition_events/
    contributions) del downgrade completo (head → base, que encadena 0002 → 0001).
    0002 NO debe tocar las tablas creadas por 0001.
    """
    original_tables = ALL_SUPPORT_TABLES - NEW_TABLES
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        url = f"sqlite:///{tmp_path.as_posix()}"
        cfg = _alembic_config(url)

        command.upgrade(cfg, "head")
        command.downgrade(cfg, "0001")
        engine = create_engine(url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert NEW_TABLES.isdisjoint(tables), "0002 no debe dejar sus tablas"
            assert original_tables <= tables, "0002 no debe tocar las tablas de 0001"
        finally:
            engine.dispose()
    finally:
        time.sleep(0.2)
        tmp_path.unlink(missing_ok=True)
