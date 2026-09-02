import json
from pathlib import Path

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.learning import _metrics, evaluate_model
from boatrace_ai.scoring import WEIGHTS, analyze_race
from boatrace_ai.storage import Repository


def test_evaluation_waits_for_enough_completed_races(tmp_path):
    report = evaluate_model(Repository(tmp_path / "empty.sqlite3"), minimum_races=200)
    assert report["status"] == "insufficient_data"
    assert report["remaining_races"] == 200


def test_metrics_rebuild_prediction_snapshot_without_future_result():
    payload = json.loads((Path(__file__).parent / "fixtures/day.json").read_text(encoding="utf-8"))
    race = BoatraceOpenApiCollector.parse(payload)[0]
    snapshot = analyze_race(race, min_confidence=0, min_margin=0).to_dict()
    row = {
        "analysis_json": json.dumps(snapshot, ensure_ascii=False),
        "result_places_json": json.dumps([1, 2, 3, 4, 5, 6]),
        "result_trifecta": "1-2-3",
    }
    metrics = _metrics([row], WEIGHTS)
    assert metrics["races"] == 1
    assert metrics["winner_accuracy"] == 1.0
    assert metrics["trifecta_hit_rate"] == 1.0
