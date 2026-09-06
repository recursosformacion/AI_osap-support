"""Port de reloj/fecha actual del dominio.

Aísla `datetime.now` para que las reglas con ventanas temporales (p. ej. la vigencia de
SUPPORTER, ADR-016) sean deterministas en tests y la producción inyecte el reloj real.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime


class Clock(ABC):
    @abstractmethod
    def utc_now(self) -> datetime:
        """Devuelve el instante actual en UTC."""
