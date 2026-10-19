from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from boatrace_ai.timing import JST

from boatrace_ai.collectors import BoatraceOpenApiCollector, CollectionError
from boatrace_ai.notifications import (
    LineNotifier, NotificationError, NotificationQuotaError, format_line_message,
)
from boatrace_ai.monitoring import collect_important_changes, format_change_message
from boatrace_ai.learning import apply_model_policy, evaluate_model
from boatrace_ai.service import run_analysis
from boatrace_ai.recommendations import build_daily_recommendations
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
    p.add_argument("--monitor-exhibition", action="store_true", help="展示後の重要変更だけを検出")
    p.add_argument("--confirm-publication", metavar="JSON", help="配信成功後だけ、保存済み版の公開時刻を確定")
    p.add_argument("--reconcile-results", type=int, default=0, metavar="LIMIT", help="公式未確定結果を上限件数まで照合")
    p.add_argument("--evaluate-model", action="store_true", help="履歴を時系列分割してモデルを検証")
    p.add_argument("--learning-report", default="artifacts/learning-report.json", help="モデル検証レポート保存先")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.confirm_publication:
        payload = json.loads(Path(args.confirm_publication).read_text(encoding="utf8"))
        repository = Repository(args.db)
        repository.confirm_publication(payload)
        return 0
    if args.reconcile_results:
        from boatrace_ai.results import reconcile
        report = reconcile(Repository(args.db),limit=max(1,args.reconcile_results))
        print(json.dumps(report,ensure_ascii=False))
        return 0
    if args.evaluate_model:
        repository = Repository(args.db)
        report = evaluate_model(repository)
        report = apply_model_policy(repository, report)
        repository.save_model_report(report)
        report_path = Path(args.learning_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"モデル検証: {report['status']} | 完了レース={report['completed_races']}")
        return 0
    try:
        race_date = date.fromisoformat(args.race_date) if args.race_date else datetime.now(JST).date()
    except ValueError:
        print("日付は YYYY-MM-DD 形式で指定してください", file=sys.stderr)
        return 2
    try:
        config_path = Path(args.config)
        config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
        configured_weights = config.get("weights")
        if configured_weights is not None and (set(configured_weights) != {"lane", "national_win_rate", "national_top2", "local_win_rate", "average_start_timing", "motor_top2", "boat_top2", "flying_count"} or abs(sum(configured_weights.values()) - 1.0) > 1e-6):
            raise ValueError("weightsは既定の8項目を持ち、合計1.0にしてください")
        repository = Repository(args.db)
        weights = repository.active_weights() or configured_weights
        analyses = run_analysis(race_date, BoatraceOpenApiCollector(), repository,
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
        recommendations = build_daily_recommendations(analyses)
        dashboard = repository.performance_payload()
        dashboard["latest_analyses"] = [a.to_dict() for a in analyses]
        dashboard["generated_at"] = datetime.now(JST).isoformat()
        candidates = repository.publication_candidates(analyses)
        dashboard["publication_candidate_ids"] = list(candidates.values())
        dashboard["publication_status"] = "prepared_not_yet_confirmed"
        for name in ("confidence_top3","value_top3"):
            for card in recommendations.get(name,[]):
                card["prediction_version"] = candidates.get((card["stadium_number"],card["race_number"]))
        dashboard["recommendations"] = recommendations
        path.write_text(json.dumps(dashboard, ensure_ascii=False, indent=2), encoding="utf-8")
    changes = collect_important_changes(analyses, repository)
    if args.monitor_exhibition:
        print(f"展示監視: 重要変更{len(changes)}件")
    exhibition_limit = 4
    exhibition_count = repository.notification_count(race_date.isoformat(), "exhibition")
    if args.notify_line and args.monitor_exhibition and changes and exhibition_count >= exhibition_limit:
        print(f"LINE通知: 展示通知は本日{exhibition_limit}通に達したため送信しません")
    elif args.notify_line and (not args.monitor_exhibition or changes):
        try:
            message = format_change_message(changes) if args.monitor_exhibition else format_line_message(analyses, race_date.isoformat())
            LineNotifier.from_environment().send(message)
            repository.record_notification(
                race_date.isoformat(), "exhibition" if args.monitor_exhibition else "morning"
            )
            print("LINE通知: 送信成功")
        except NotificationQuotaError as exc:
            # LINEの上限到達で、予想JSON・SQLite・GitHub Pagesの更新まで止めない。
            print(f"LINE通知: {exc}", file=sys.stderr)
        except NotificationError as exc:
            print(f"LINE通知: {exc}", file=sys.stderr)
            return 1
    elif args.notify_line and args.monitor_exhibition:
        print("LINE通知: 重要変更なしのため送信しません")
    return 0
