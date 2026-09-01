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

