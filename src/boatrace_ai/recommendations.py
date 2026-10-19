from __future__ import annotations

from datetime import datetime, timedelta, timezone

from boatrace_ai.models import RaceAnalysis

JST = timezone(timedelta(hours=9), name="Asia/Tokyo")


def _upcoming(analysis: RaceAnalysis, now: datetime) -> bool:
    race = analysis.race
    if race.result_trifecta is not None:
        return False
    from boatrace_ai.timing import upcoming
    return upcoming(race.closed_at,now)


def _card(analysis: RaceAnalysis, recommendation_score: float, reasons: list[str],
          category: str) -> dict:
    race = analysis.race
    return {
        "category": category,
        "stadium_number": race.stadium_number,
        "stadium_name": race.stadium_name,
        "race_number": race.race_number,
        "closed_at": race.closed_at,
        "favorite_lane": analysis.favorite_lane,
        "dark_horse_lane": analysis.dark_horse_lane,
        "trifectas": analysis.trifectas,
        "confidence": analysis.confidence,
        "confidence_kind":"heuristic_score_not_probability",
        "hit_probability":None,"expected_value":None,"odds_at_prediction":None,
        "fetched_at":race.fetched_at,
        "stage":"post_exhibition" if len(race.entrants)==6 and all(e.exhibition_time is not None for e in race.entrants) else "pre_exhibition",
        "data_completeness": analysis.data_completeness,
        "recommendation_score": round(recommendation_score, 3),
        "reasons": reasons,
        "wind_speed": race.wind_speed,
        "wave_height": race.wave_height,
    }


def build_daily_recommendations(analyses: list[RaceAnalysis], now: datetime | None = None,
                                limit: int = 3) -> dict:
    now = now or datetime.now(JST)
    eligible = [item for item in analyses if _upcoming(item, now) and item.decision == "買い候補"]

    confident_ranked = []
    value_ranked = []
    for item in eligible:
        if len(item.scores) < 2:
            continue
        margin = max(0.0, item.scores[0].score - item.scores[1].score)
        confident_score = item.confidence * 0.60 + item.data_completeness * 0.25 \
                           + min(margin / 12.0, 1.0) * 0.15
        confident_ranked.append((confident_score, item, [
            f"confidence {item.confidence:.1%}",
            f"データ充足率 {item.data_completeness:.1%}",
            f"上位スコア差 {margin:.2f}",
        ]))

        dark = next((score for score in item.scores if score.lane == item.dark_horse_lane), None)
        favorite = next((score for score in item.scores if score.lane == item.favorite_lane), None)
        if not dark or not favorite or dark.lane < 4 or favorite.score <= 0:
            continue
        competitiveness = min(dark.score / favorite.score, 1.0)
        outer_bonus = (dark.lane - 3) / 3
        value_score = competitiveness * 0.55 + outer_bonus * 0.25 + item.confidence * 0.20
        value_ranked.append((value_score, item, [
            f"{dark.lane}号艇の穴候補スコア {dark.score:.2f}",
            f"本命艇に対するスコア比 {competitiveness:.1%}",
            "実オッズ未連携のため選手・枠・展示スコアによる推定",
        ]))

    confident_ranked.sort(key=lambda row: row[0], reverse=True)
    value_ranked.sort(key=lambda row: row[0], reverse=True)
    return {
        "generated_at": now.isoformat(),
        "confidence_top3": [_card(item, score, reasons, "本日の分析スコア上位")
                            for score, item, reasons in confident_ranked[:limit]],
        "value_top3": [_card(item, score, reasons, "配当妙味あり！（推定）")
                       for score, item, reasons in value_ranked[:limit]],
        "value_basis": "odds_unavailable_score_proxy",
        "expected_value":None,"odds_status":"unavailable",
        "notice": "配当妙味は実オッズではなく外枠穴候補と分析スコアによる推定です。",
    }
