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


def registry(dance):
    return [
        Tool(
            name="dance",
            description=(
                "「みくみくにしてあげる♪」を踊る。踊ってと頼まれたときに使う。"
                "踊りは今の返事を読み上げ終わってから始まる。"
            ),
            input_schema={"type": "object", "properties": {}},
            handler=dance,
        ),
    ]
