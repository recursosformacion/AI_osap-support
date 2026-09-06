"""Reloj real (UTC) del sistema para osap-support.

Implementa `domain.ports.clock.Clock`; en tests se inyecta un reloj fijo.
"""

from __future__ import annotations

from datetime import UTC, datetime

from domain.ports.clock import Clock


class SystemClock(Clock):
    def utc_now(self) -> datetime:
        return datetime.now(UTC)
