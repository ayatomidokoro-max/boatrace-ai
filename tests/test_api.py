from __future__ import annotations

from boatrace_ai.api import _payload
from boatrace_ai.models import EntrantScore, Race, RaceAnalysis
from boatrace_ai.storage import Repository


def test_api_payload_returns_latest_completed_run(tmp_path):
    repository = Repository(tmp_path / "api.sqlite3")
    run_id = repository.start_run("2026-09-01", "2026-09-01T10:00:00+09:00", "https://example.test")
    analysis = RaceAnalysis(
        race=Race("2026-09-01", 1, "桐生", 1, closed_at="10:30"),
        scores=[EntrantScore(1, 1234, "選手A", 80.0, 0.8, ["1コース"] )],
        confidence=0.7, data_completeness=0.8, decision="買い候補",
        favorite_lane=1, dark_horse_lane=None, trifectas=["1-2-3"], reasons=["基準を満たしました"],
    )
    repository.save(run_id, analysis)
    repository.finish_run(run_id, "completed")

    payload = _payload(repository, "2026-09-01")

    assert payload["status"] == "ok"
    assert payload["analyses"][0]["stadium_name"] == "桐生"
    assert payload["analyses"][0]["trifectas"] == ["1-2-3"]
    assert payload["analyses"][0]["scores"][0]["racer_name"] == "選手A"


def test_api_payload_marks_missing_data(tmp_path):
    payload = _payload(Repository(tmp_path / "empty.sqlite3"), "2026-09-01")
    assert payload == {"status": "no_data", "run": None, "analyses": []}
