"""The tools saru may use, kept independent of any brain.

One tool is a name, a description for the model, a JSON schema of its input,
and an async handler that takes the input dict and returns the text the model
gets back. A brain turns this table into whatever its SDK wants (ClaudeBrain:
an in-process MCP server). New tools (home appliances, ...) are added here.
"""

from dataclasses import dataclass
from typing import Awaitable, Callable

Handler = Callable[[dict], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Handler


def registry(weather, calendar_events, calendar_add):
    return [
        Tool(
            name="weather",
            description=(
                "家の天気を調べる。今の雨（降水強度と降り出すまでの分）、1時間ごとの予報、"
                "日ごとの予報をまとめて JSON で返す。時刻は日本時間。天気・気温・雨を聞かれたときに使う。"
                "同じ会話で続けて聞かれたら、さっき取ったデータで答えてよい。"
                "雨は降るかどうか、降る時間帯、強さで答え、確率は言わない。"
            ),
            input_schema={"type": "object", "properties": {}},
            handler=weather,
        ),
        Tool(
            name="calendar_events",
            description=(
                "ユーザーの Google カレンダーの予定を、start_date から days 日分調べて JSON で返す。時刻は日本時間。"
                "予定・スケジュール・用事を聞かれたときに使う。「来週」は次の月曜から7日間。"
                "all_day の予定は first_day から last_day まで（last_day が無ければその日だけ）。"
                "began_before_range は期間より前から続いている予定なので、そう分かるように言う。"
                "予定が無ければ無いと答える。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "start_date": {"type": "string", "description": "最初の日（YYYY-MM-DD）"},
                    "days": {"type": "integer", "minimum": 1, "description": "何日分か（既定 1）"},
                },
                "required": ["start_date"],
            },
            handler=calendar_events,
        ),
        Tool(
            name="calendar_add",
            description=(
                "ユーザーの Google カレンダーに予定を1件追加する。予定を入れて・登録して、と頼まれたときに使う。"
                "呼ぶ前に必ず日付・時刻・件名を復唱して確かめ、ユーザーが「はい」などと認めてから呼ぶ。"
                "時刻が分からなければ聞き返すか、終日の予定にしてよいか確かめる。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "件名"},
                    "start": {
                        "type": "string",
                        "description": "開始。時刻ありは YYYY-MM-DDTHH:MM（日本時間）、終日は YYYY-MM-DD",
                    },
                    "end": {
                        "type": "string",
                        "description": "終了（任意）。時刻ありは YYYY-MM-DDTHH:MM で省くと1時間、終日は最終日の YYYY-MM-DD で省くと1日",
                    },
                    "location": {"type": "string", "description": "場所（任意）"},
                },
                "required": ["summary", "start"],
            },
            handler=calendar_add,
        ),
    ]
