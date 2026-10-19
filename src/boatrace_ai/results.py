"""Conservative, bounded reconciliation against public official results; no betting API."""
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from boatrace_ai.timing import instant, JST


class ResultTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.cells, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.cells = []
        elif tag in ("td", "th") and self.cells is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.cells.append(re.sub(r"\s+", "", "".join(self.cell)))
            self.cell = None
        elif tag == "tr" and self.cells is not None:
            self.rows.append(self.cells)
            self.cells = None


def parse_official(html: str) -> dict:
    parser = ResultTable()
    parser.feed(html)
    matches = []
    for cells in parser.rows:
        if len(cells) >= 3 and cells[0] == "3連単":
            combination = cells[1]
            amount = re.sub(r"[¥￥,]", "", cells[2])
            if re.fullmatch(r"[1-6]-[1-6]-[1-6]", combination) and amount.isdigit():
                if len(set(combination.split("-"))) == 3:
                    matches.append((combination,int(amount)))
    if len(matches) == 1:
        combination, amount = matches[0]
        return {"status":"official_confirmed","combination":combination,"payout":amount,
                "places":[int(n) for n in combination.split("-")]}
    # Multiple winners/refunds are deliberately not guessed as a single winning ticket.
    if re.search(r"このレースは(?:中止|不成立)|レースは中止となりました", html):
        return {"status":"cancelled"}
    return {"status":"unparsed" if matches else "not_published"}


def fetch_official(race: dict) -> tuple[str, dict]:
    url = ("https://www.boatrace.jp/owpc/pc/race/raceresult?hd="
           + race["race_date"].replace("-", "")
           + f'&jcd={race["stadium_number"]:02d}&rno={race["race_number"]}')
    try:
        request = Request(url,headers={"User-Agent":"boatrace-ai/0.2 result verification (no betting)"})
        with urlopen(request,timeout=15) as response:
            html = response.read().decode("utf-8")
        return url, parse_official(html)
    except Exception as exc:
        return url, {"status":"fetch_error","detail":type(exc).__name__}


def reconcile(repository, limit: int = 8, fetch=fetch_official) -> dict:
    now = datetime.now(UTC)
    with repository.connect() as db:
        db.row_factory = __import__("sqlite3").Row
        rows = db.execute("""SELECT p.*, c.checked_at,c.status AS checked_status
            FROM race_predictions p LEFT JOIN race_results r
            USING(race_date,stadium_number,race_number)
            LEFT JOIN result_checks c USING(race_date,stadium_number,race_number)
            WHERE r.result_trifecta IS NULL
            ORDER BY COALESCE(c.checked_at,''),p.race_date,p.stadium_number,p.race_number""").fetchall()
    counts = {}
    checked = 0
    for raw in rows:
        race = dict(raw)
        deadline = instant(race["closed_at"],JST)
        prior = instant(race["checked_at"])
        if not deadline or deadline > now-timedelta(minutes=30):
            continue
        if race["checked_status"] == "cancelled" or (prior and prior > now-timedelta(days=1)):
            continue
        url, result = fetch(race)
        status = result["status"]
        with repository.connect() as db:
            key = (race["race_date"],race["stadium_number"],race["race_number"])
            if status == "official_confirmed":
                import json
                db.execute("""INSERT INTO race_results (race_date,stadium_number,race_number,
                    result_trifecta,trifecta_payout,result_places_json,recorded_at)
                    VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                    (*key,result["combination"],result["payout"],json.dumps(result["places"]),now.isoformat()))
            db.execute("""INSERT INTO result_checks VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(race_date,stadium_number,race_number) DO UPDATE SET
                status=excluded.status,checked_at=excluded.checked_at,
                source_url=excluded.source_url,detail=excluded.detail""",
                (*key,status,now.isoformat(),url,result.get("detail")))
        counts[status] = counts.get(status,0)+1
        checked += 1
        if checked >= limit:
            break
    return {"checked":checked,"statuses":counts}
