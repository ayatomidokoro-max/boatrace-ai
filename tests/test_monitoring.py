import copy
import json
from pathlib import Path

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.monitoring import collect_important_changes, exhibition_ready, format_change_message
from boatrace_ai.scoring import analyze_race
from boatrace_ai.storage import Repository


def analysis_from(payload):
    return analyze_race(BoatraceOpenApiCollector.parse(payload)[0], min_confidence=0, min_margin=0)


def test_preview_fields_are_parsed(fixture_payload):
    analysis = analysis_from(fixture_payload)
    assert exhibition_ready(analysis)
    assert analysis.race.wind_speed == 3
    assert analysis.race.entrants[0].exhibition_time == 6.70


def test_first_snapshot_does_not_notify_and_change_deduplicates(tmp_path, fixture_payload):
    repo = Repository(tmp_path / "monitor.sqlite3")
    baseline = copy.deepcopy(fixture_payload)
    # 朝の状態として展示を外す。
    baseline["programs"]["stadiums"]["5"]["races"]["1"].pop("preview")
    assert collect_important_changes([analysis_from(baseline)], repo) == []

    changed = copy.deepcopy(fixture_payload)
    race = changed["programs"]["stadiums"]["5"]["races"]["1"]
    race["preview"]["racers"]["4"]["course_number"] = 2
    changes = collect_important_changes([analysis_from(changed)], repo)
    assert len(changes) == 1
    assert "進入変更あり" in changes[0].reasons
    assert "重要変更" in format_change_message(changes)

    assert collect_important_changes([analysis_from(changed)], repo) == []


def test_no_exhibition_does_not_notify(tmp_path, fixture_payload):
    repo = Repository(tmp_path / "none.sqlite3")
    payload = copy.deepcopy(fixture_payload)
    payload["programs"]["stadiums"]["5"]["races"]["1"].pop("preview")
    analysis = analysis_from(payload)
    assert not exhibition_ready(analysis)
    assert collect_important_changes([analysis], repo) == []

