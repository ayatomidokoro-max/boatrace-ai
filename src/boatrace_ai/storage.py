from __future__ import annotations

import json
import sqlite3
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
"""


class Repository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(SCHEMA)
        return connection

    def start_run(self, race_date: str, started_at: str, source_url: str) -> int:
        with self.connect() as db:
            cursor = db.execute("INSERT INTO runs(race_date,started_at,source_url,status) VALUES(?,?,?,'running')",
                                (race_date, started_at, source_url))
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, status: str, error: str | None = None) -> None:
        with self.connect() as db:
            db.execute("UPDATE runs SET status=?, error=? WHERE id=?", (status, error, run_id))

    def save(self, run_id: int, analysis: RaceAnalysis) -> None:
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
            if race.result_trifecta is None:
                db.execute("""INSERT INTO race_predictions
                    (race_date,stadium_number,race_number,stadium_name,predicted_at,closed_at,
                     decision,favorite_lane,dark_horse_lane,confidence,data_completeness,
                     trifectas_json,analysis_json)
                    VALUES(?,?,?,?,datetime('now'),?,?,?,?,?,?,?,?)
                    ON CONFLICT(race_date,stadium_number,race_number) DO UPDATE SET
                    stadium_name=excluded.stadium_name,predicted_at=excluded.predicted_at,
                    closed_at=excluded.closed_at,decision=excluded.decision,
                    favorite_lane=excluded.favorite_lane,dark_horse_lane=excluded.dark_horse_lane,
                    confidence=excluded.confidence,data_completeness=excluded.data_completeness,
                    trifectas_json=excluded.trifectas_json,analysis_json=excluded.analysis_json""",
                    (race.race_date, race.stadium_number, race.race_number, race.stadium_name,
                     race.closed_at, analysis.decision, analysis.favorite_lane, analysis.dark_horse_lane,
                     analysis.confidence, analysis.data_completeness,
                     json.dumps(analysis.trifectas, ensure_ascii=False),
                     json.dumps(analysis.to_dict(), ensure_ascii=False)))
            else:
                db.execute("""INSERT INTO race_results
                    (race_date,stadium_number,race_number,result_trifecta,trifecta_payout,
                     result_places_json,wind_speed,wave_height,air_temperature,water_temperature,recorded_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,datetime('now'))
                    ON CONFLICT(race_date,stadium_number,race_number) DO UPDATE SET
                    result_trifecta=excluded.result_trifecta,trifecta_payout=excluded.trifecta_payout,
                    result_places_json=excluded.result_places_json,wind_speed=excluded.wind_speed,
                    wave_height=excluded.wave_height,air_temperature=excluded.air_temperature,
                    water_temperature=excluded.water_temperature,recorded_at=excluded.recorded_at""",
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
        for row in rows:
            item = dict(row)
            trifectas = json.loads(item.pop("trifectas_json"))
            item["trifectas"] = trifectas
            item["analysis"] = json.loads(item.pop("analysis_json"))
            result_places_json = item.pop("result_places_json")
            item["result_places"] = json.loads(result_places_json) if result_places_json else []
            if item["result_trifecta"] is None:
                outcome, stake, returned = "未確定", 0, 0
            elif item["decision"] != "買い候補":
                outcome, stake, returned = "見送り", 0, 0
            else:
                hit = item["result_trifecta"] in trifectas
                outcome = "的中" if hit else "不的中"
                stake = 100 * len(trifectas)
                returned = int(item["trifecta_payout"] or 0) if hit else 0
            item.update({"outcome": outcome, "stake": stake, "return": returned})
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
        }, "model_evaluation": self.latest_model_report()}

    def learning_rows(self) -> list[dict]:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("""SELECT p.race_date,p.stadium_number,p.analysis_json,
                r.result_places_json,r.result_trifecta,r.wind_speed,r.wave_height
                FROM race_predictions p JOIN race_results r
                USING(race_date,stadium_number,race_number)
                ORDER BY p.race_date,p.stadium_number,p.race_number""").fetchall()
        return [dict(row) for row in rows]

    def save_model_report(self, report: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO model_reports(created_at,report_json) VALUES(datetime('now'),?)",
                       (json.dumps(report, ensure_ascii=False),))

    def latest_model_report(self) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT report_json FROM model_reports ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None
