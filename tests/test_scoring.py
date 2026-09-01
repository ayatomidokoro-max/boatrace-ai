import json
from pathlib import Path

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.models import Entrant
from boatrace_ai.scoring import analyze_race, score_entrant


def fixture_race():
    payload = json.loads((Path(__file__).parent / "fixtures/day.json").read_text(encoding="utf-8"))
    return BoatraceOpenApiCollector.parse(payload)[0]


def test_missing_values_are_not_treated_as_zero():
    missing = score_entrant(Entrant(lane=1))
    actual_zero = score_entrant(Entrant(lane=1, national_win_rate=0.0))
    assert missing.score > actual_zero.score
    assert missing.data_completeness == 0.0


def test_analysis_has_favorite_dark_horse_and_trifectas():
    result = analyze_race(fixture_race(), min_confidence=0.0, min_margin=0.0)
    assert result.favorite_lane == 1
    assert result.dark_horse_lane == 4
    assert result.trifectas
    assert all(ticket.startswith("1-") for ticket in result.trifectas)
    assert result.data_completeness == 1.0


def test_incomplete_race_is_skipped():
    race = fixture_race()
    for entrant in race.entrants:
        entrant.national_win_rate = None
        entrant.national_top2 = None
        entrant.local_win_rate = None
        entrant.average_start_timing = None
        entrant.motor_top2 = None
        entrant.boat_top2 = None
        entrant.flying_count = None
    assert analyze_race(race).decision == "見送り"

