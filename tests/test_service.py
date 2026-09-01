import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from boatrace_ai.collectors.base import Collector
from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.service import run_analysis
from boatrace_ai.storage import Repository


class FixtureCollector(Collector):
    def collect(self, race_date):
        payload = json.loads((Path(__file__).parent / "fixtures/day.json").read_text(encoding="utf-8"))
        return BoatraceOpenApiCollector.parse(payload)


class BrokenCollector(Collector):
    def collect(self, race_date):
        raise RuntimeError("boom")


def test_service_end_to_end(tmp_path):
    repo = Repository(tmp_path / "ok.sqlite3")
    analyses = run_analysis(date(2026, 9, 1), FixtureCollector(), repo, 0, 0)
    assert len(analyses) == 1


def test_failure_is_recorded(tmp_path):
    repo = Repository(tmp_path / "failed.sqlite3")
    with pytest.raises(RuntimeError):
        run_analysis(date(2026, 9, 1), BrokenCollector(), repo)
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT status FROM runs").fetchone()[0] == "failed"

