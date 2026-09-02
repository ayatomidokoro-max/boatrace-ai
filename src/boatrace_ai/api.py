from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from boatrace_ai.storage import Repository
from boatrace_ai.venues import VENUES


def _payload(repository: Repository, race_date: str | None = None) -> dict:
    run = repository.latest_run(race_date)
    if not run:
        return {"status": "no_data", "run": None, "analyses": []}
    analyses = repository.analyses_for_run(run["id"])
    for item in analyses:
        item["stadium_name"] = VENUES.get(item["stadium_number"], "未取得")
    return {"status": "ok", "run": run, "analyses": analyses}


def make_handler(repository: Repository, api_key: str | None, allowed_origins: set[str]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "BoatraceReadOnlyAPI/1.0"

        def _origin(self) -> str | None:
            origin = self.headers.get("Origin")
            return origin if origin and origin in allowed_origins else None

        def _send(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self._origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not api_key:
                return True
            return self.headers.get("Authorization") == f"Bearer {api_key}"

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                jst = timezone(timedelta(hours=9), name="Asia/Tokyo")
                self._send(200, {"status": "ok", "time": datetime.now(jst).isoformat()})
                return
            if not self._authorized():
                self._send(401, {"status": "error", "message": "unauthorized"})
                return
            if parsed.path == "/api/v1/analyses":
                race_date = parse_qs(parsed.query).get("date", [None])[0]
                self._send(200, _payload(repository, race_date))
                return
            if parsed.path == "/api/v1/performance":
                self._send(200, {"status": "ok", **repository.performance_payload()})
                return
            if parsed.path.startswith("/api/v1/races/"):
                parts = parsed.path.strip("/").split("/")
                if len(parts) != 6:
                    self._send(404, {"status": "error", "message": "not_found"})
                    return
                race_date, stadium, race_number = parts[3:]
                payload = _payload(repository, race_date)
                try:
                    match = next(item for item in payload["analyses"]
                                 if item["stadium_number"] == int(stadium)
                                 and item["race_number"] == int(race_number))
                except (ValueError, StopIteration):
                    self._send(404, {"status": "error", "message": "race_not_found"})
                    return
                self._send(200, {"status": "ok", "run": payload["run"], "analysis": match})
                return
            self._send(404, {"status": "error", "message": "not_found"})

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="ボートレース分析結果の参照専用API")
    command.add_argument("--db", default="data/boatrace.sqlite3")
    command.add_argument("--host", default=os.getenv("BOATRACE_API_HOST", "127.0.0.1"))
    command.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    return command


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    api_key = os.getenv("BOATRACE_API_KEY")
    if args.host not in {"127.0.0.1", "localhost", "::1"} and not api_key:
        print("外部公開する場合はBOATRACE_API_KEYが必要です")
        return 2
    origins = {value.strip() for value in os.getenv("BOATRACE_ALLOWED_ORIGINS", "").split(",") if value.strip()}
    handler = make_handler(Repository(args.db), api_key, origins)
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Read-only API listening on http://{args.host}:{args.port}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
