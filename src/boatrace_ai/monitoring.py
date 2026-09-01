from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from boatrace_ai.models import RaceAnalysis
from boatrace_ai.storage import Repository


@dataclass(slots=True)
class ImportantChange:
    analysis: RaceAnalysis
    reasons: list[str]
    signature: str


def exhibition_ready(analysis: RaceAnalysis) -> bool:
    entrants = analysis.race.entrants
    return len(entrants) == 6 and all(item.exhibition_time is not None for item in entrants)


def detect_important_change(previous: dict, current: RaceAnalysis) -> list[str]:
    reasons: list[str] = []
    if previous.get("decision") != current.decision:
        reasons.append(f"判定変更: {previous.get('decision')}→{current.decision}")
    if previous.get("favorite_lane") != current.favorite_lane:
        reasons.append(f"本命変更: {previous.get('favorite_lane')}号艇→{current.favorite_lane}号艇")
    if previous.get("dark_horse_lane") != current.dark_horse_lane:
        reasons.append(f"穴候補変更: {previous.get('dark_horse_lane')}号艇→{current.dark_horse_lane}号艇")
    old_confidence = float(previous.get("confidence", 0))
    if abs(old_confidence - current.confidence) >= 0.12:
        reasons.append(f"confidence変動: {old_confidence:.1%}→{current.confidence:.1%}")
    if any(e.exhibition_course is not None and e.exhibition_course != e.lane for e in current.race.entrants):
        reasons.append("進入変更あり")
    if (current.race.wind_speed or 0) >= 8 or (current.race.wave_height or 0) >= 10:
        reasons.append("強風・高波")
    return reasons


def collect_important_changes(analyses: list[RaceAnalysis], repository: Repository) -> list[ImportantChange]:
    changes: list[ImportantChange] = []
    for analysis in analyses:
        race = analysis.race
        state = repository.get_monitoring_state(race.race_date, race.stadium_number, race.race_number)
        if state is None:
            repository.save_monitoring_state(analysis, None)
            continue
        if not exhibition_ready(analysis):
            repository.save_monitoring_state(analysis, None)
            continue
        reasons = detect_important_change(state["snapshot"], analysis)
        signature_source = "|".join([race.race_date, str(race.stadium_number), str(race.race_number), *reasons])
        signature = hashlib.sha256(signature_source.encode()).hexdigest()
        if reasons and signature != state.get("last_notified_signature"):
            changes.append(ImportantChange(analysis, reasons, signature))
            repository.save_monitoring_state(analysis, signature)
        else:
            repository.save_monitoring_state(analysis, None)
    return changes


def format_change_message(changes: list[ImportantChange]) -> str:
    lines = [f"【展示後の重要変更 {datetime.now():%Y-%m-%d %H:%M}】"]
    for change in changes[:8]:
        item = change.analysis
        lines.extend([
            "",
            f"{item.race.stadium_name} {item.race.race_number}R",
            " / ".join(change.reasons),
            f"本命 {item.favorite_lane}号艇｜穴 {item.dark_horse_lane}号艇｜信頼度 {item.confidence:.1%}",
            f"3連単 {', '.join(item.trifectas) or 'なし'}",
        ])
    lines.extend(["", "※重要変更があったレースのみ通知。自動投票は行いません。"])
    return "\n".join(lines)[:5000]

