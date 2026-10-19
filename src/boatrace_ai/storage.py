from __future__ import annotations

import json
import sqlite3
import hashlib
from datetime import UTC, datetime
from boatrace_ai.timing import eligibility
from pathlib import Path

from boatrace_ai.models import RaceAnalysis

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, race_date TEXT NOT NULL, started_at TEXT NOT NULL,
 source_url TEXT, status TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id),
 stadium_number INTEGER NOT NULL, race_number INTEGER NOT NULL,
 closed_at TEXT, decision TEXT NOT NULL, favorite_lane INTEGER,
 dark_horse_lane INTEGER, confidence REAL NOT NULL, data_completeness REAL NOT NULL,
 trifectas_json TEXT NOT NULL, reasons_json TEXT NOT NULL,
 UNIQUE(run_id, stadium_number, race_number)
);
CREATE TABLE IF NOT EXISTS entrant_scores (
 analysis_id INTEGER NOT NULL REFERENCES analyses(id), lane INTEGER NOT NULL,
 racer_number INTEGER, racer_name TEXT, score REAL NOT NULL,
 data_completeness REAL NOT NULL, reasons_json TEXT NOT NULL,
 PRIMARY KEY(analysis_id, lane)
);
CREATE TABLE IF NOT EXISTS monitoring_states (
 race_date TEXT NOT NULL, stadium_number INTEGER NOT NULL, race_number INTEGER NOT NULL,
 snapshot_json TEXT NOT NULL, last_notified_signature TEXT,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(race_date, stadium_number, race_number)
);
CREATE TABLE IF NOT EXISTS race_predictions (
 race_date TEXT NOT NULL, stadium_number INTEGER NOT NULL, race_number INTEGER NOT NULL,
 stadium_name TEXT NOT NULL, predicted_at TEXT NOT NULL, closed_at TEXT,
 decision TEXT NOT NULL, favorite_lane INTEGER, dark_horse_lane INTEGER,
 confidence REAL NOT NULL, data_completeness REAL NOT NULL,
 trifectas_json TEXT NOT NULL, analysis_json TEXT NOT NULL,
 PRIMARY KEY(race_date,stadium_number,race_number)
);
CREATE TABLE IF NOT EXISTS race_results (
 race_date TEXT NOT NULL, stadium_number INTEGER NOT NULL, race_number INTEGER NOT NULL,
 result_trifecta TEXT NOT NULL, trifecta_payout INTEGER, result_places_json TEXT NOT NULL,
 wind_speed REAL, wave_height REAL, air_temperature REAL, water_temperature REAL,
 recorded_at TEXT NOT NULL,
 PRIMARY KEY(race_date,stadium_number,race_number)
);
CREATE TABLE IF NOT EXISTS model_reports (
 id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, report_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS model_policy (
 id INTEGER PRIMARY KEY CHECK(id=1), state_json TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_migrations (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS legacy_prediction_keys (
 race_date TEXT NOT NULL, stadium_number INTEGER NOT NULL, race_number INTEGER NOT NULL,
 PRIMARY KEY(race_date,stadium_number,race_number)
);
CREATE TABLE IF NOT EXISTS prediction_versions (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id),
 race_date TEXT NOT NULL, stadium_number INTEGER NOT NULL, race_number INTEGER NOT NULL,
 predicted_at TEXT NOT NULL, fetched_at TEXT, stage TEXT NOT NULL,
 model_version TEXT NOT NULL, selection_json TEXT NOT NULL, analysis_json TEXT NOT NULL,
 published_at TEXT, recommendation_categories_json TEXT NOT NULL DEFAULT '[]',
 UNIQUE(run_id,stadium_number,race_number)
);
CREATE INDEX IF NOT EXISTS prediction_versions_race ON prediction_versions(race_date,stadium_number,race_number);
CREATE TABLE IF NOT EXISTS result_checks (
 race_date TEXT NOT NULL, stadium_number INTEGER NOT NULL, race_number INTEGER NOT NULL,
 status TEXT NOT NULL, checked_at TEXT NOT NULL, source_url TEXT NOT NULL, detail TEXT,
 PRIMARY KEY(race_date,stadium_number,race_number)
);
CREATE TABLE IF NOT EXISTS notification_deliveries (
 id INTEGER PRIMARY KEY, race_date TEXT NOT NULL, kind TEXT NOT NULL,
 sent_at TEXT NOT NULL
);
"""


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)
        with connection:
            if not connection.execute("SELECT 1 FROM audit_migrations WHERE version=1").fetchone():
                connection.execute("INSERT OR IGNORE INTO legacy_prediction_keys SELECT race_date,stadium_number,race_number FROM race_predictions")
                connection.execute("INSERT INTO audit_migrations VALUES(1)")
        return connection

    def start_run(self, race_date: str, started_at: str, source_url: str) -> int:
        with self.connect() as db:
            cursor = db.execute("INSERT INTO runs(race_date,started_at,source_url,status) VALUES(?,?,?,'running')",
                                (race_date, started_at, source_url))
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, error: str | None = None) -> None:
        with self.connect() as db:
            db.execute("UPDATE runs SET status=?, error=? WHERE id=?", (status, error, run_id))

    def save(self, run_id: int, analysis: RaceAnalysis, *, selection: dict | None = None,
             model_version: str = "baseline") -> None:
        race = analysis.race
        with self.connect() as db:
            cursor = db.execute("""INSERT INTO analyses
                (run_id,stadium_number,race_number,closed_at,decision,favorite_lane,dark_horse_lane,
                 confidence,data_completeness,trifectas_json,reasons_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, race.stadium_number, race.race_number, race.closed_at, analysis.decision,
                 analysis.favorite_lane, analysis.dark_horse_lane, analysis.confidence,
                 analysis.data_completeness, json.dumps(analysis.trifectas, ensure_ascii=False),
                 json.dumps(analysis.reasons, ensure_ascii=False)))
            analysis_id = int(cursor.lastrowid)
            db.executemany("""INSERT INTO entrant_scores
                (analysis_id,lane,racer_number,racer_name,score,data_completeness,reasons_json)
                VALUES(?,?,?,?,?,?,?)""", [(analysis_id, s.lane, s.racer_number, s.racer_name,
                s.score, s.data_completeness, json.dumps(s.reasons, ensure_ascii=False)) for s in analysis.scores])
            if race.result_trifecta is None and not race.result_places:
                stage = "post_exhibition" if len(race.entrants) == 6 and all(
                    e.exhibition_time is not None for e in race.entrants) else "pre_exhibition"
                db.execute("""INSERT INTO prediction_versions
                    (run_id,race_date,stadium_number,race_number,predicted_at,fetched_at,
                     stage,model_version,selection_json,analysis_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?)""", (run_id,race.race_date,race.stadium_number,
                    race.race_number,datetime.now(UTC).isoformat(),race.fetched_at,stage,
                    model_version,json.dumps(selection or {"min_confidence":0.62,"min_margin":4.0}),
                    json.dumps(analysis.to_dict(),ensure_ascii=False)))
                db.execute("""INSERT INTO race_predictions
                    (race_date,stadium_number,race_number,stadium_name,predicted_at,closed_at,
                     decision,favorite_lane,dark_horse_lane,confidence,data_completeness,
                     trifectas_json,analysis_json)
                    VALUES(?,?,?,?,datetime('now'),?,?,?,?,?,?,?,?)
                    ON CONFLICT(race_date,stadium_number,race_number) DO NOTHING""",
                    (race.race_date, race.stadium_number, race.race_number, race.stadium_name,
                     race.closed_at, analysis.decision, analysis.favorite_lane, analysis.dark_horse_lane,
                     analysis.confidence, analysis.data_completeness,
                     json.dumps(analysis.trifectas, ensure_ascii=False),
                     json.dumps(analysis.to_dict(), ensure_ascii=False)))
            elif race.result_trifecta is not None:
                db.execute("""INSERT INTO race_results
                    (race_date,stadium_number,race_number,result_trifecta,trifecta_payout,
                     result_places_json,wind_speed,wave_height,air_temperature,water_temperature,recorded_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(race_date,stadium_number,race_number) DO UPDATE SET
                    result_trifecta=excluded.result_trifecta,trifecta_payout=excluded.trifecta_payout,
                    result_places_json=excluded.result_places_json,wind_speed=excluded.wind_speed,
                    wave_height=excluded.wave_height,air_temperature=excluded.air_temperature,
                    water_temperature=excluded.water_temperature,recorded_at=excluded.recorded_at
                    WHERE NOT EXISTS (SELECT 1 FROM result_checks c WHERE
                        c.race_date=excluded.race_date AND c.stadium_number=excluded.stadium_number
                        AND c.race_number=excluded.race_number AND c.status='official_confirmed')""",
                    (race.race_date, race.stadium_number, race.race_number, race.result_trifecta,
                     race.trifecta_payout, json.dumps(race.result_places), race.wind_speed,
                     race.wave_height, race.air_temperature, race.water_temperature))

    def get_monitoring_state(self, race_date: str, stadium_number: int, race_number: int) -> dict | None:
        with self.connect() as db:
            row = db.execute("""SELECT snapshot_json,last_notified_signature FROM monitoring_states
                WHERE race_date=? AND stadium_number=? AND race_number=?""",
                (race_date, stadium_number, race_number)).fetchone()
        return {"snapshot": json.loads(row[0]), "last_notified_signature": row[1]} if row else None

    def save_monitoring_state(self, analysis: RaceAnalysis, signature: str | None) -> None:
        race = analysis.race
        snapshot = {
            "decision": analysis.decision, "favorite_lane": analysis.favorite_lane,
            "dark_horse_lane": analysis.dark_horse_lane, "confidence": analysis.confidence,
            "scores": {str(score.lane): score.score for score in analysis.scores},
        }
        with self.connect() as db:
            db.execute("""INSERT INTO monitoring_states
                (race_date,stadium_number,race_number,snapshot_json,last_notified_signature,updated_at)
                VALUES(?,?,?,?,?,datetime('now'))
                ON CONFLICT(race_date,stadium_number,race_number) DO UPDATE SET
                snapshot_json=excluded.snapshot_json,
                last_notified_signature=COALESCE(excluded.last_notified_signature,monitoring_states.last_notified_signature),
                updated_at=excluded.updated_at""",
                (race.race_date, race.stadium_number, race.race_number,
                 json.dumps(snapshot, ensure_ascii=False), signature))

    def latest_run(self, race_date: str | None = None) -> dict | None:
        query = """SELECT id,race_date,started_at,source_url,status,error FROM runs
            WHERE status IN ('success','completed')"""
        params: tuple[object, ...] = ()
        if race_date:
            query += " AND race_date=?"
            params = (race_date,)
        query += " ORDER BY id DESC LIMIT 1"
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute(query, params).fetchone()
        return dict(row) if row else None

    def analyses_for_run(self, run_id: int) -> list[dict]:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT id,stadium_number,race_number,closed_at,decision,
                favorite_lane,dark_horse_lane,confidence,data_completeness,trifectas_json,reasons_json
                FROM analyses WHERE run_id=? ORDER BY stadium_number,race_number""", (run_id,)).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                analysis_id = item.pop("id")
                item["trifectas"] = json.loads(item.pop("trifectas_json"))
                item["reasons"] = json.loads(item.pop("reasons_json"))
                scores = db.execute("""SELECT lane,racer_number,racer_name,score,data_completeness,reasons_json
                    FROM entrant_scores WHERE analysis_id=? ORDER BY lane""", (analysis_id,)).fetchall()
                item["scores"] = [{**dict(score), "reasons": json.loads(score["reasons_json"])}
                                  for score in scores]
                for score in item["scores"]:
                    score.pop("reasons_json")
                results.append(item)
        return results

    def performance_payload(self) -> dict:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT p.*,r.result_trifecta,r.trifecta_payout,
                r.result_places_json,r.wind_speed,r.wave_height,r.air_temperature,r.water_temperature
                FROM race_predictions p LEFT JOIN race_results r USING(race_date,stadium_number,race_number)
                ORDER BY p.race_date DESC,p.stadium_number,p.race_number""").fetchall()
        races = []
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            legacy_keys = set(map(tuple,db.execute("SELECT * FROM legacy_prediction_keys")))
            versions = db.execute("SELECT * FROM prediction_versions ORDER BY id").fetchall()
            checks = {tuple(row[k] for k in ("race_date","stadium_number","race_number")):dict(row)
                      for row in db.execute("SELECT * FROM result_checks")}
        versioned_keys = set()
        published = {}
        for version in versions:
            v = dict(version)
            versioned_keys.add((v["race_date"],v["stadium_number"],v["race_number"]))
            a = json.loads(v["analysis_json"])
            if v["published_at"] and eligibility(v["published_at"],a["race"].get("closed_at")) == "eligible":
                published[(v["race_date"],v["stadium_number"],v["race_number"])] = (v,a)
        for row in rows:
            item = dict(row)
            key = (item["race_date"],item["stadium_number"],item["race_number"])
            selected = published.get(key)
            item.update({"prediction_version":None,"stage":"legacy_first_snapshot","selection":{
                "min_confidence":0.62,"min_margin":4.0},"published_at":None})
            if selected:
                version, analysis = selected
                for field in ("decision","favorite_lane","dark_horse_lane","confidence","data_completeness"):
                    item[field] = analysis[field]
                item["analysis_json"] = version["analysis_json"]
                item["trifectas_json"] = json.dumps(analysis["trifectas"])
                item["predicted_at"] = version["predicted_at"]
                item["closed_at"] = analysis["race"].get("closed_at")
                item.update({"prediction_version":version["id"],"stage":version["stage"],
                    "published_at":version["published_at"],"model_version":version["model_version"],
                    "selection":json.loads(version["selection_json"]),
                    "recommendation_categories":json.loads(version["recommendation_categories_json"])})
            item["evaluation_status"] = eligibility(item["published_at"] or item["predicted_at"],item["closed_at"])
            if key in versioned_keys and key not in legacy_keys and selected is None:
                item["evaluation_status"] = "unpublished_before_deadline"
            check = checks.get(key,{})
            item["result_status"] = check.get("status") or ("confirmed_secondary" if item["result_trifecta"] else "unfetched")
            item["result_source_url"] = check.get("source_url")
            item["odds_at_prediction"] = None
            item["final_odds"] = None
            item["expected_value"] = None
            trifectas = json.loads(item.pop("trifectas_json"))
            item["trifectas"] = trifectas
            item["analysis"] = json.loads(item.pop("analysis_json"))
            result_places_json = item.pop("result_places_json")
            item["result_places"] = json.loads(result_places_json) if result_places_json else []
            if item["evaluation_status"] != "eligible":
                outcome, stake, returned = "評価除外", 0, 0
            elif item["result_status"] == "cancelled":
                outcome, stake, returned = "中止", 0, 0
            elif item["result_trifecta"] is None:
                outcome, stake, returned = "未確定", 0, 0
            elif item["decision"] != "買い候補":
                outcome, stake, returned = "見送り", 0, 0
            else:
                hit = item["result_trifecta"] in trifectas
                outcome = "的中" if hit else "不的中"
                stake = 100 * len(trifectas)
                returned = int(item["trifecta_payout"] or 0) if hit else 0
            item.update({
                "outcome": outcome,
                "hit": True if outcome == "的中" else False if outcome == "不的中" else None,
                "stake": stake,
                "return": returned,
            })
            races.append(item)

        def aggregate(key):
            groups: dict[str, dict] = {}
            for item in races:
                if item["outcome"] not in {"的中", "不的中"}:
                    continue
                label = key(item)
                group = groups.setdefault(label, {"bets": 0, "hits": 0, "stake": 0, "return": 0})
                group["bets"] += 1
                group["hits"] += item["outcome"] == "的中"
                group["stake"] += item["stake"]
                group["return"] += item["return"]
            for group in groups.values():
                group["hit_rate"] = round(group["hits"] / group["bets"] * 100, 2) if group["bets"] else None
                group["recovery_rate"] = round(group["return"] / group["stake"] * 100, 2) if group["stake"] else None
            return groups

        return {"races": races, "summary": {
            "daily": aggregate(lambda x: x["race_date"]),
            "monthly": aggregate(lambda x: x["race_date"][:7]),
            "yearly": aggregate(lambda x: x["race_date"][:4]),
            "by_stadium": aggregate(lambda x: x["stadium_name"]),
        }, "model_evaluation": self.latest_model_report(),
        "evaluation_policy": {"version":"deadline-published-v2","stake_per_ticket":100,
            "basis":"latest_published_before_deadline_or_legacy_first",
            "confidence_is_probability":False,"odds_status":"unavailable"},
        "audit_counts": {"total":len(races),"excluded":sum(r["evaluation_status"]!="eligible" for r in races),
            "unresolved":sum(r["result_trifecta"] is None and r["result_status"]!="cancelled" for r in races)}}

    def publication_candidates(self, analyses: list[RaceAnalysis]) -> dict:
        candidates = {}
        with self.connect() as db:
            for a in analyses:
                r = a.race
                row = db.execute("""SELECT id,analysis_json FROM prediction_versions WHERE race_date=?
                    AND stadium_number=? AND race_number=? ORDER BY id DESC LIMIT 1""",
                    (r.race_date,r.stadium_number,r.race_number)).fetchone()
                if row and json.loads(row[1]) == a.to_dict():
                    candidates[(r.stadium_number,r.race_number)] = row[0]
        return candidates

    def confirm_publication(self, payload: dict) -> None:
        """Called only after successful deployment; publication cannot be backdated."""
        allowed = {json.dumps(a,sort_keys=True) for a in payload["latest_analyses"]}
        ids = set(payload.get("publication_candidate_ids",[]))
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            for row in db.execute("SELECT * FROM prediction_versions WHERE published_at IS NULL").fetchall():
                if row["id"] not in ids or json.dumps(json.loads(row["analysis_json"]),sort_keys=True) not in allowed:
                    continue
                categories = [name for name in ("confidence_top3","value_top3") if any(
                    card.get("prediction_version")==row["id"] for card in payload["recommendations"].get(name,[]))]
                db.execute("UPDATE prediction_versions SET published_at=?,recommendation_categories_json=? WHERE id=?",
                           (datetime.now(UTC).isoformat(),json.dumps(categories),row["id"]))

    def publish_predictions(self, analyses: list[RaceAnalysis], recommendations: dict) -> None:
        candidates = self.publication_candidates(analyses)
        for name in ("confidence_top3","value_top3"):
            for card in recommendations.get(name,[]):
                card["prediction_version"] = candidates.get((card["stadium_number"],card["race_number"]))
        self.confirm_publication({"latest_analyses":[a.to_dict() for a in analyses],
            "publication_candidate_ids":list(candidates.values()),"recommendations":recommendations})

    def learning_rows(self) -> list[dict]:
        rows = []
        for item in self.performance_payload()["races"]:
            if item["evaluation_status"] != "eligible" or len(item["result_places"]) < 3:
                continue
            rows.append({**item,"analysis_json":json.dumps(item["analysis"]),
                         "result_places_json":json.dumps(item["result_places"])})
        return sorted(rows,key=lambda x:(x["race_date"],x["stadium_number"],x["race_number"]))

    def save_model_report(self, report: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO model_reports(created_at,report_json) VALUES(datetime('now'),?)",
                       (json.dumps(report, ensure_ascii=False),))

    def latest_model_report(self) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT report_json FROM model_reports ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def get_model_policy(self) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT state_json FROM model_policy WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}

    def save_model_policy(self, state: dict) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO model_policy(id,state_json,updated_at)
                VALUES(1,?,datetime('now')) ON CONFLICT(id) DO UPDATE SET
                state_json=excluded.state_json,updated_at=excluded.updated_at""",
                (json.dumps(state, ensure_ascii=False),))

    def active_weights(self) -> dict[str, float] | None:
        weights = self.get_model_policy().get("active_weights")
        return {key: float(value) for key, value in weights.items()} if weights else None

    def notification_count(self, race_date: str, kind: str) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM notification_deliveries WHERE race_date=? AND kind=?",
                (race_date, kind),
            ).fetchone()
        return int(row[0])

    def record_notification(self, race_date: str, kind: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO notification_deliveries(race_date,kind,sent_at) VALUES(?,?,datetime('now'))",
                (race_date, kind),
            )
