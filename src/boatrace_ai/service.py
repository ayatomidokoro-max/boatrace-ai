from __future__ import annotations

from datetime import UTC, date, datetime

from boatrace_ai.collectors.base import Collector
from boatrace_ai.scoring import analyze_race
from boatrace_ai.storage import Repository


def run_analysis(race_date: date, collector: Collector, repository: Repository,
                 min_confidence: float = 0.62, min_margin: float = 4.0,
                 weights: dict[str, float] | None = None):
    source_url = getattr(collector, "url_for", lambda _: "unknown")(race_date)
    run_id = repository.start_run(race_date.isoformat(), datetime.now(UTC).isoformat(), source_url)
    try:
        analyses = [analyze_race(race, min_confidence, min_margin, weights) for race in collector.collect(race_date)]
        for analysis in analyses:
            repository.save(run_id, analysis)
        repository.finish_run(run_id, "success")
        return analyses
    except Exception as exc:
        repository.finish_run(run_id, "failed", str(exc))
        raise
