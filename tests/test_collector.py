import json
from pathlib import Path

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector


def test_parse_fixture_all_fields():
    payload = json.loads((Path(__file__).parent / "fixtures/day.json").read_text(encoding="utf-8"))
    races = BoatraceOpenApiCollector.parse(payload)
    assert len(races) == 1
    assert races[0].stadium_name == "多摩川"
    assert len(races[0].entrants) == 6
    assert races[0].entrants[3].motor_top2 == 48.0


def test_empty_payload_is_safe():
    assert BoatraceOpenApiCollector.parse({}) == []


def test_result_weather_and_trifecta_are_used_when_preview_is_missing():
    payload = {"programs": {"stadiums": {"1": {"races": {"1": {
        "date": "2026-09-02", "stadium_number": 1, "race_number": 1,
        "racers": {}, "result": {
            "wind_speed": 4, "wave_height": 3, "air_temperature": 28.0,
            "water_temperature": 27.0,
            "racers": {"1": {"entry_number": 1, "place_number": 2},
                       "3": {"entry_number": 3, "place_number": 1},
                       "5": {"entry_number": 5, "place_number": 3}},
            "payouts": {"trifecta": [{"combination": "3-1-5", "amount": 2040}]},
        },
    }}}}}}
    race = BoatraceOpenApiCollector.parse(payload)[0]
    assert race.wind_speed == 4
    assert race.wave_height == 3
    assert race.result_trifecta == "3-1-5"
    assert race.trifecta_payout == 2040
    assert race.result_places == [3, 1, 5]
