from __future__ import annotations

from itertools import permutations

from boatrace_ai.models import Entrant, EntrantScore, Race, RaceAnalysis

FEATURES = (
    "national_win_rate", "national_top2", "local_win_rate",
    "average_start_timing", "motor_top2", "boat_top2", "flying_count",
)
WEIGHTS = {
    "lane": 0.22, "national_win_rate": 0.20, "national_top2": 0.12,
    "local_win_rate": 0.14, "average_start_timing": 0.14,
    "motor_top2": 0.10, "boat_top2": 0.06, "flying_count": 0.02,
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_entrant(entrant: Entrant, weights: dict[str, float] | None = None) -> EntrantScore:
    weights = weights or WEIGHTS
    values: dict[str, float] = {"lane": _clamp((7 - entrant.lane) / 6)}
    reasons = [f"{entrant.lane}号艇の枠補正"]
    transforms = {
        "national_win_rate": lambda x: x / 10,
        "national_top2": lambda x: x / 100,
        "local_win_rate": lambda x: x / 10,
        "average_start_timing": lambda x: 1 - x / 0.30,
        "motor_top2": lambda x: x / 100,
        "boat_top2": lambda x: x / 100,
        "flying_count": lambda x: 1 - x / 2,
    }
    present_weight = weights["lane"]
    weighted = values["lane"] * weights["lane"]
    for name in FEATURES:
        raw = getattr(entrant, name)
        if raw is None:
            continue
        normalized = _clamp(transforms[name](float(raw)))
        weighted += normalized * weights[name]
        present_weight += weights[name]
        if name in ("national_win_rate", "local_win_rate", "average_start_timing", "motor_top2"):
            reasons.append(f"{name}={raw}")
    # 欠損は0点にせず、存在する項目の重みだけで再正規化する。
    score = 100 * weighted / present_weight
    completeness = sum(getattr(entrant, name) is not None for name in FEATURES) / len(FEATURES)
    return EntrantScore(entrant.lane, entrant.racer_number, entrant.racer_name,
                        round(score, 2), round(completeness, 3), reasons)


def analyze_race(race: Race, min_confidence: float = 0.62, min_margin: float = 4.0,
                 weights: dict[str, float] | None = None) -> RaceAnalysis:
    scores = sorted((score_entrant(e, weights) for e in race.entrants), key=lambda x: x.score, reverse=True)
    completeness = sum(s.data_completeness for s in scores) / len(scores) if scores else 0.0
    entrant_factor = min(1.0, len(scores) / 6)
    margin = scores[0].score - scores[1].score if len(scores) > 1 else 0.0
    separation = min(1.0, margin / 12)
    confidence = round(completeness * entrant_factor * (0.75 + 0.25 * separation), 3)
    reasons = [f"データ充足率 {completeness:.1%}", f"上位スコア差 {margin:.2f}"]
    decision = "買い候補" if confidence >= min_confidence and margin >= min_margin else "見送り"
    if decision == "見送り":
        reasons.append("confidenceまたは上位スコア差が基準未達")
    favorite = scores[0].lane if scores else None
    # 穴候補は外枠(4〜6)のうち最高点。いなければ3位艇。
    outside = [s for s in scores if s.lane >= 4]
    dark_horse = outside[0].lane if outside else (scores[2].lane if len(scores) >= 3 else None)
    top_lanes = [s.lane for s in scores[:4]]
    trifectas = ["-".join(map(str, combo)) for combo in permutations(top_lanes, 3)
                 if combo[0] == favorite][:6]
    return RaceAnalysis(race, scores, confidence, round(completeness, 3), decision,
                        favorite, dark_horse, trifectas, reasons)
