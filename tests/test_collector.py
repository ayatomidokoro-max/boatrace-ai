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

