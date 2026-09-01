import json
from pathlib import Path

import pytest


@pytest.fixture
def fixture_payload():
    return json.loads((Path(__file__).parent / "fixtures/day.json").read_text(encoding="utf-8"))

