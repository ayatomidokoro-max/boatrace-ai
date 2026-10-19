import json
from pathlib import Path

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.learning import _metrics, apply_model_policy, evaluate_model
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
        "trifecta_payout": 1800,
    }
    metrics = _metrics([row], WEIGHTS)
    assert metrics["races"] == 1
    assert metrics["winner_accuracy"] == 1.0
    assert metrics["trifecta_hit_rate"] == 1.0
    assert metrics["stake"] == 600
    assert metrics["return"] == 1800
    assert metrics["recovery_rate"] == 300.0


def _recommended_report(created_at: str):
    candidate = {key: value for key, value in WEIGHTS.items()}
    candidate["lane"] -= 0.01
    candidate["national_win_rate"] += 0.01
    return {
        "created_at": created_at, "status": "candidate_recommended",
        "candidate_weights": candidate,
        "candidate_validation": {"recovery_rate": 120.0, "trifecta_hit_rate": 0.20},
        "baseline_validation": {"recovery_rate": 100.0, "trifecta_hit_rate": 0.19},
        "auto_applied": False,
    }


def test_repeated_overlapping_reports_cannot_promote_model(tmp_path):
    repository = Repository(tmp_path / "policy.sqlite3")
    for day in ("2026-09-01","2026-09-08"):
        report = apply_model_policy(repository, _recommended_report(day))
        assert report["policy_action"] == "maintained"
        assert report["auto_applied"] is False
        assert repository.active_weights() is None


def test_policy_preserves_existing_active_weights(tmp_path):
    repository = Repository(tmp_path / "policy.sqlite3")
    repository.save_model_policy({"status":"active","active_weights":WEIGHTS})
    apply_model_policy(repository,_recommended_report("2026-09-08"))
    assert repository.active_weights() == WEIGHTS
