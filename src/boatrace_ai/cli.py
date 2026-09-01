from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from boatrace_ai.collectors import BoatraceOpenApiCollector, CollectionError
from boatrace_ai.notifications import LineNotifier, NotificationError, format_line_message
from boatrace_ai.service import run_analysis
from boatrace_ai.storage import Repository


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="全国ボートレース分析（自動投票機能なし）")
    p.add_argument("--date", dest="race_date", help="開催日 YYYY-MM-DD（省略時はJST当日）")
    p.add_argument("--db", default="data/boatrace.sqlite3", help="SQLite保存先")
    p.add_argument("--json", dest="json_path", help="全分析結果JSONの保存先")
    p.add_argument("--config", default="config/scoring.json", help="採点設定JSON")
    p.add_argument("--min-confidence", type=float, default=0.62)
    p.add_argument("--min-margin", type=float, default=4.0)
    p.add_argument("--notify-line", action="store_true", help="分析結果を個人LINEへ送信")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        race_date = date.fromisoformat(args.race_date) if args.race_date else datetime.now(ZoneInfo("Asia/Tokyo")).date()
    except ValueError:
        print("日付は YYYY-MM-DD 形式で指定してください", file=sys.stderr)
        return 2
    try:
        config_path = Path(args.config)
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        weights = config.get("weights")
        if weights is not None and (set(weights) != {"lane", "national_win_rate", "national_top2", "local_win_rate", "average_start_timing", "motor_top2", "boat_top2", "flying_count"} or abs(sum(weights.values()) - 1.0) > 1e-6):
            raise ValueError("weightsは既定の8項目を持ち、合計1.0にしてください")
        analyses = run_analysis(race_date, BoatraceOpenApiCollector(), Repository(args.db),
                                args.min_confidence, args.min_margin, weights)
    except (CollectionError, ValueError, json.JSONDecodeError) as exc:
        print(f"取得失敗（安全に終了）: {exc}", file=sys.stderr)
        return 1
    candidates = [a for a in analyses if a.decision == "買い候補"]
    favorite = max(candidates, key=lambda a: a.confidence, default=None)
    dark = max((a for a in candidates if a.dark_horse_lane is not None),
               key=lambda a: next((s.score for s in a.scores if s.lane == a.dark_horse_lane), 0), default=None)
    print(f"{race_date} | {len(analyses)}レース収集 | 候補{len(candidates)} | 見送り{len(analyses)-len(candidates)}")
    for label, item in (("本命候補", favorite), ("穴候補", dark)):
        if item:
            r = item.race
            lane = item.favorite_lane if label == "本命候補" else item.dark_horse_lane
            print(f"{label}: {r.stadium_name}{r.race_number}R {lane}号艇 confidence={item.confidence:.3f} "
                  f"completeness={item.data_completeness:.3f} 3連単={','.join(item.trifectas)}")
        else:
            print(f"{label}: 見送り（基準を満たすレースなし）")
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([a.to_dict() for a in analyses], ensure_ascii=False, indent=2), encoding="utf-8")
    if args.notify_line:
        try:
            LineNotifier.from_environment().send(format_line_message(analyses, race_date.isoformat()))
            print("LINE通知: 送信成功")
        except NotificationError as exc:
            print(f"LINE通知: {exc}", file=sys.stderr)
            return 1
    return 0
