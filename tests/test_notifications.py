import json

import pytest

from boatrace_ai.collectors.open_api import BoatraceOpenApiCollector
from boatrace_ai.notifications import LineNotifier, NotificationError, format_line_message
from boatrace_ai.scoring import analyze_race


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_line_request_does_not_put_secret_in_body(fixture_payload):
    captured = {}

    def opener(request, timeout):
        captured["request"] = request
        return FakeResponse()

    notifier = LineNotifier("secret-token", "U123", opener=opener)
    notifier.send("テスト通知")
    request = captured["request"]
    body = json.loads(request.data.decode("utf-8"))
    assert body == {"to": "U123", "messages": [{"type": "text", "text": "テスト通知"}]}
    assert b"secret-token" not in request.data
    assert request.get_header("Authorization") == "Bearer secret-token"


def test_missing_credentials_are_rejected():
    with pytest.raises(NotificationError):
        LineNotifier("", "")


def test_message_contains_candidate_and_disclaimer(fixture_payload):
    race = BoatraceOpenApiCollector.parse(fixture_payload)[0]
    analysis = analyze_race(race, min_confidence=0, min_margin=0)
    text = format_line_message([analysis], race.race_date)
    assert "本命候補" in text
    assert "多摩川 1R" in text
    assert "自動投票は行いません" in text

