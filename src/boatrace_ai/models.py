from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class Entrant:
    lane: int
    racer_number: int | None = None
    racer_name: str | None = None
    rank: str | None = None
    age: int | None = None
    national_win_rate: float | None = None
    national_top2: float | None = None
    local_win_rate: float | None = None
    average_start_timing: float | None = None
    motor_top2: float | None = None
    boat_top2: float | None = None
    flying_count: int | None = None


@dataclass(slots=True)
class Race:
    race_date: str
    stadium_number: int
    stadium_name: str
    race_number: int
    closed_at: str | None = None
    grade: str | None = None
    title: str | None = None
    subtitle: str | None = None
    day_number: int | None = None
    entrants: list[Entrant] = field(default_factory=list)
    source_url: str = ""
    fetched_at: str = ""


@dataclass(slots=True)
class EntrantScore:
    lane: int
    racer_number: int | None
    racer_name: str | None
    score: float
    data_completeness: float
    reasons: list[str]


@dataclass(slots=True)
class RaceAnalysis:
    race: Race
    scores: list[EntrantScore]
    confidence: float
    data_completeness: float
    decision: str
    favorite_lane: int | None
    dark_horse_lane: int | None
    trifectas: list[str]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

