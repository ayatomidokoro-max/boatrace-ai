import json
import sqlite3
from datetime import date
from pathlib import Path

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.scoring import analyze_race
from boatrace_ai.storage import Repository


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

