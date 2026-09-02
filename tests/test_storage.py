import json
import sqlite3
from datetime import date
from pathlib import Path

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.scoring import analyze_race
from boatrace_ai.storage import Repository


def _analysis(race, trifectas=None, decision="買い候補"):
    from boatrace_ai.models import EntrantScore, RaceAnalysis
    return RaceAnalysis(race, [EntrantScore(1, 1001, "選手", 80, 1, [])], 0.8, 1,
                        decision, 1, 4, trifectas or ["1-2-3"], [])


def test_save_analysis(tmp_path):
    payload = json.loads((Path(__file__).parent / "fixtures/day.json").read_text(encoding="utf-8"))
    analysis = analyze_race(BoatraceOpenApiCollector.parse(payload)[0])
    repo = Repository(tmp_path / "test.sqlite3")
    run_id = repo.start_run(date.today().isoformat(), "now", "fixture")
    repo.save(run_id, analysis)
    repo.finish_run(run_id, "success")
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT status FROM runs").fetchone()[0] == "success"
        assert db.execute("SELECT COUNT(*) FROM analyses").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM entrant_scores").fetchone()[0] == 6


def test_prediction_is_frozen_and_performance_is_aggregated(tmp_path):
    from boatrace_ai.models import Race
    repository = Repository(tmp_path / "history.sqlite3")
    run = repository.start_run("2026-09-02", "now", "source")
    repository.save(run, _analysis(Race("2026-09-02", 1, "桐生", 1)))
    repository.finish_run(run, "success")
    result_run = repository.start_run("2026-09-02", "later", "source")
    repository.save(result_run, _analysis(Race("2026-09-02", 1, "桐生", 1,
        result_trifecta="1-2-3", trifecta_payout=1800, result_places=[1, 2, 3])))
    repository.finish_run(result_run, "success")

    payload = repository.performance_payload()
    race = payload["races"][0]
    assert race["outcome"] == "的中"
    assert race["stake"] == 100
    assert race["return"] == 1800
    assert payload["summary"]["daily"]["2026-09-02"]["hit_rate"] == 100.0
    assert payload["summary"]["daily"]["2026-09-02"]["recovery_rate"] == 1800.0
