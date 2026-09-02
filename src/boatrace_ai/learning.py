from __future__ import annotations

import json
import random
from datetime import UTC, datetime

from boatrace_ai.models import Entrant, Race
from boatrace_ai.scoring import WEIGHTS, analyze_race
from boatrace_ai.storage import Repository


def _race_from_snapshot(snapshot: dict) -> Race:
    raw = snapshot["race"]
    fields = Race.__dataclass_fields__
    values = {key: value for key, value in raw.items() if key in fields and key != "entrants"}
    values["entrants"] = [Entrant(**entrant) for entrant in raw.get("entrants", [])]
    return Race(**values)


def _metrics(rows: list[dict], weights: dict[str, float]) -> dict:
    winner_hits = trifecta_hits = evaluated = 0
    for row in rows:
        places = json.loads(row["result_places_json"])
        if len(places) < 3:
            continue
        race = _race_from_snapshot(json.loads(row["analysis_json"]))
        analysis = analyze_race(race, min_confidence=0.0, min_margin=0.0, weights=weights)
        evaluated += 1
        winner_hits += analysis.favorite_lane == places[0]
        trifecta_hits += row["result_trifecta"] in analysis.trifectas
    return {
        "races": evaluated,
        "winner_accuracy": round(winner_hits / evaluated, 4) if evaluated else None,
        "trifecta_hit_rate": round(trifecta_hits / evaluated, 4) if evaluated else None,
    }


def _candidates(baseline: dict[str, float], count: int = 240) -> list[dict[str, float]]:
    rng = random.Random(20260902)
    candidates = [baseline]
    for _ in range(count - 1):
        raw = {name: max(0.005, weight * rng.uniform(0.45, 1.75)) for name, weight in baseline.items()}
        total = sum(raw.values())
        candidates.append({name: value / total for name, value in raw.items()})
    return candidates


def evaluate_model(repository: Repository, minimum_races: int = 200) -> dict:
    rows = repository.learning_rows()
    completed = len(rows)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "completed_races": completed,
        "minimum_races": minimum_races,
        "status": "insufficient_data",
        "message": f"検証可能な結果が{minimum_races}件に達するまで現行モデルを維持します。",
        "baseline_weights": WEIGHTS,
    }
    if completed < minimum_races:
        report["remaining_races"] = minimum_races - completed
        return report

    split = max(1, int(completed * 0.8))
    train, validation = rows[:split], rows[split:]
    baseline_train = _metrics(train, WEIGHTS)
    baseline_validation = _metrics(validation, WEIGHTS)
    scored = []
    for weights in _candidates(WEIGHTS):
        metrics = _metrics(train, weights)
        objective = (metrics["winner_accuracy"] or 0) * 0.65 + (metrics["trifecta_hit_rate"] or 0) * 0.35
        scored.append((objective, weights, metrics))
    _, candidate_weights, candidate_train = max(scored, key=lambda item: item[0])
    candidate_validation = _metrics(validation, candidate_weights)
    winner_gain = (candidate_validation["winner_accuracy"] or 0) - (baseline_validation["winner_accuracy"] or 0)
    trifecta_gain = (candidate_validation["trifecta_hit_rate"] or 0) - (baseline_validation["trifecta_hit_rate"] or 0)
    recommended = winner_gain >= 0.02 and trifecta_gain >= -0.01
    report.update({
        "status": "candidate_recommended" if recommended else "keep_current",
        "message": "検証用データでも改善を確認しました。人の確認後に採用できます。" if recommended
                   else "検証用データで明確な改善がないため現行モデルを維持します。",
        "train_races": len(train), "validation_races": len(validation),
        "baseline_train": baseline_train, "baseline_validation": baseline_validation,
        "candidate_weights": {key: round(value, 6) for key, value in candidate_weights.items()},
        "candidate_train": candidate_train, "candidate_validation": candidate_validation,
        "winner_accuracy_gain": round(winner_gain, 4),
        "trifecta_hit_rate_gain": round(trifecta_gain, 4),
        "auto_applied": False,
    })
    return report
