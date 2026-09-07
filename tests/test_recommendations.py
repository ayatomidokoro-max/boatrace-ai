import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.recommendations import build_daily_recommendations
from boatrace_ai.scoring import analyze_race

JST = timezone(timedelta(hours=9))


def _analyses(count=5):
    payload = json.loads((Path(__file__).parent / "fixtures/day.json").read_text(encoding="utf-8"))
    base = BoatraceOpenApiCollector.parse(payload)[0]
    items = []
    for number in range(1, count + 1):
        race = deepcopy(base)
        race.race_number = number
        race.closed_at = f"2026-09-01 {13 + number:02d}:00:00"
        items.append(analyze_race(race, min_confidence=0, min_margin=0))
    return items


def test_recommendations_are_limited_to_three_each():
    result = build_daily_recommendations(
        _analyses(), datetime(2026, 9, 1, 12, tzinfo=JST))
    assert len(result["confidence_top3"]) == 3
    assert len(result["value_top3"]) == 3
    assert result["value_basis"] == "odds_unavailable_score_proxy"


def test_finished_or_closed_races_are_excluded():
    items = _analyses(1)
    items[0].race.closed_at = "2026-09-01 11:00:00"
    result = build_daily_recommendations(
        items, datetime(2026, 9, 1, 12, tzinfo=JST))
    assert result["confidence_top3"] == []
    assert result["value_top3"] == []
