from __future__ import annotations

import json
import os
from collections.abc import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from boatrace_ai.models import RaceAnalysis

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class NotificationError(RuntimeError):
    """通知設定または送信に失敗した。秘密情報は例外文に含めない。"""


def _top_candidates(analyses: list[RaceAnalysis]) -> tuple[RaceAnalysis | None, RaceAnalysis | None]:
    candidates = [item for item in analyses if item.decision == "買い候補"]
    favorite = max(candidates, key=lambda item: item.confidence, default=None)
    dark = max(
        (item for item in candidates if item.dark_horse_lane is not None),
        key=lambda item: next(
            (score.score for score in item.scores if score.lane == item.dark_horse_lane), 0
        ),
        default=None,
    )
    return favorite, dark


def format_line_message(analyses: list[RaceAnalysis], race_date: str) -> str:
    """個人LINE向けの短い結果通知を生成する。"""
    candidates = [item for item in analyses if item.decision == "買い候補"]
    favorite, dark = _top_candidates(analyses)
    lines = [
        f"【ボートレース分析 {race_date}】",
        f"全{len(analyses)}R｜候補{len(candidates)}R｜見送り{len(analyses) - len(candidates)}R",
    ]
    if favorite is None:
        lines.extend(["", "本日は基準を満たす候補がありません。", "判定：見送り"])
        return "\n".join(lines)

    race = favorite.race
    lines.extend([
        "",
        "■ 本命候補",
        f"{race.stadium_name} {race.race_number}R｜{favorite.favorite_lane}号艇",
        f"信頼度 {favorite.confidence:.1%}｜充足率 {favorite.data_completeness:.1%}",
        f"3連単候補 {', '.join(favorite.trifectas) or 'なし'}",
    ])
    if dark is not None:
        race = dark.race
        lines.extend([
            "",
            "■ 穴候補",
            f"{race.stadium_name} {race.race_number}R｜{dark.dark_horse_lane}号艇",
            f"信頼度 {dark.confidence:.1%}｜充足率 {dark.data_completeness:.1%}",
        ])
    lines.extend(["", "※自動投票は行いません。最終確認はBOAT RACE公式で行ってください。"])
    return "\n".join(lines)


class LineNotifier:
    def __init__(
        self,
        channel_access_token: str,
        user_id: str,
        opener: Callable = urlopen,
        timeout: float = 20,
    ):
        if not channel_access_token or not user_id:
            raise NotificationError("LINE_CHANNEL_ACCESS_TOKENとLINE_USER_IDが必要です")
        self._token = channel_access_token
        self._user_id = user_id
        self._opener = opener
        self._timeout = timeout

    @classmethod
    def from_environment(cls) -> "LineNotifier":
        return cls(
            os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", ""),
            os.environ.get("LINE_USER_ID", ""),
        )

    def send(self, text: str) -> None:
        if not text or len(text) > 5000:
            raise NotificationError("LINE通知文は1〜5000文字にしてください")
        body = json.dumps(
            {"to": self._user_id, "messages": [{"type": "text", "text": text}]},
            ensure_ascii=False,
        ).encode("utf-8")
        request = Request(
            LINE_PUSH_URL,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "boatrace-ai/0.2",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise NotificationError(f"LINE送信に失敗しました（HTTP {status}）")
        except HTTPError as exc:
            raise NotificationError(f"LINE送信に失敗しました（HTTP {exc.code}）") from exc
        except (URLError, TimeoutError) as exc:
            raise NotificationError("LINE送信に失敗しました（通信エラー）") from exc

