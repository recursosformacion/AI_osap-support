"""Tests de migración Alembic 0001 (Fase 3).

Se ejecuta upgrade y downgrade contra una BD SQLite temporal aislada (solo tests;
producción usa MariaDB/osap_support según ADR-003). Verifica que upgrade crea las
tablas del dominio y que downgrade las elimina (reversible). No toca BD externas.
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

EXPECTED_TABLES = {
    "support_members",
    "memberships",
    "donations",
    "payment_events",
    "communication_events",
}


def _alembic_config(sqlite_url: str) -> Config:
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", "infrastructure/db/alembic")
    cfg.set_main_option("sqlalchemy.url", sqlite_url)
    cfg.set_main_option("prepend_sys_path", ".")
    return cfg


def test_upgrade_creates_support_tables_and_downgrade_drops_them() -> None:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        url = f"sqlite:///{tmp_path.as_posix()}"
        cfg = _alembic_config(url)

        command.upgrade(cfg, "head")
        engine = create_engine(url)
        try:
            tables = set(inspect(engine).get_table_names())
            assert EXPECTED_TABLES <= tables

            pk_columns = inspect(engine).get_pk_constraint("payment_events")[
                "constrained_columns"
            ]
            assert pk_columns == ["id"]
            uq = inspect(engine).get_unique_constraints("payment_events")
            assert any(
                set(c["column_names"]) == {"provider", "provider_event_id"} for c in uq
            )
        finally:
            engine.dispose()

        command.downgrade(cfg, "base")
        engine = create_engine(url)
        try:
            tables_after = set(inspect(engine).get_table_names())
            assert EXPECTED_TABLES.isdisjoint(tables_after)
        finally:
            engine.dispose()
    finally:
        time.sleep(0.2)
        tmp_path.unlink(missing_ok=True)
