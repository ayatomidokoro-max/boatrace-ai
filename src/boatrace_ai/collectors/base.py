from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from boatrace_ai.models import Race


class Collector(ABC):
    @abstractmethod
    def collect(self, race_date: date) -> list[Race]: ...

