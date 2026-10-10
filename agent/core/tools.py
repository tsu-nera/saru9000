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


def registry(weather):
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
    ]
