from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from boatrace_ai.collectors.base import Collector
from boatrace_ai.models import Entrant, Race
from boatrace_ai.venues import VENUES


class CollectionError(RuntimeError):
    pass


class BoatraceOpenApiCollector(Collector):
    """非公式Boatrace Open API用collector。差し替え可能な境界に隔離する。"""

    base_url = "https://boatraceopenapi.github.io/api/v1"

    def __init__(self, timeout: float = 20, retries: int = 3):
        self.timeout = timeout
        self.retries = retries

    def url_for(self, race_date: date) -> str:
        return f"{self.base_url}/{race_date:%Y}/{race_date:%Y%m%d}.json"

    def collect(self, race_date: date) -> list[Race]:
        url = self.url_for(race_date)
        request = Request(url, headers={"User-Agent": "boatrace-ai/0.1 (+data-analysis; no-betting)"})
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                return self.parse(payload, url)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(0.5 * (2**attempt))
        raise CollectionError(f"データ取得に失敗しました: {url}: {last_error}")

    @staticmethod
    def parse(payload: dict, source_url: str = "fixture") -> list[Race]:
        fetched_at = datetime.now(UTC).isoformat()
        stadiums = payload.get("programs", {}).get("stadiums", {})
        races: list[Race] = []
        for stadium_key, stadium in stadiums.items():
            for race_key, raw in stadium.get("races", {}).items():
                stadium_number = int(raw.get("stadium_number", stadium_key))
                entrants = []
                for lane_key, racer in raw.get("racers", {}).items():
                    entrants.append(Entrant(
                        lane=int(racer.get("entry_number", lane_key)),
                        racer_number=racer.get("number"), racer_name=racer.get("name"),
                        rank=racer.get("rank_number_source"), age=racer.get("age"),
                        national_win_rate=racer.get("national_win_rate"),
                        national_top2=racer.get("national_top_2_percent"),
                        local_win_rate=racer.get("local_win_rate"),
                        average_start_timing=racer.get("average_start_timing"),
                        motor_top2=racer.get("motor_top_2_percent"),
                        boat_top2=racer.get("boat_top_2_percent"),
                        flying_count=racer.get("flying_count"),
                    ))
                races.append(Race(
                    race_date=raw.get("date", ""), stadium_number=stadium_number,
                    stadium_name=VENUES.get(stadium_number, f"場{stadium_number}"),
                    race_number=int(raw.get("race_number", race_key)), closed_at=raw.get("closed_at"),
                    grade=raw.get("grade_number_source"), title=raw.get("title"),
                    subtitle=raw.get("subtitle"), day_number=raw.get("day_number"),
                    entrants=sorted(entrants, key=lambda item: item.lane),
                    source_url=source_url, fetched_at=fetched_at,
                ))
        return sorted(races, key=lambda race: (race.stadium_number, race.race_number))

