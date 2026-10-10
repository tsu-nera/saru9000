"""The tools saru may use, kept independent of any brain.

One tool is a name, a description for the model, a JSON schema of its input,
and an async handler that takes the input dict and returns the text the model
gets back. A brain turns this table into whatever its SDK wants (ClaudeBrain:
an in-process MCP server). New tools are added here.
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


def field_line(key, field):
    """One script field for run_action's description: key, what it is, and its choices."""
    text = "、".join(t for t in (field.get("name"), field.get("description")) if t)
    selector = field.get("selector") or {}
    choices = None
    if "select" in selector:
        options = (selector["select"] or {}).get("options", [])
        choices = [
            f"{o['value']}（{o['label']}）" if isinstance(o, dict) else str(o) for o in options
        ]
    elif "boolean" in selector:
        choices = ["true", "false"]
    line = f"    - {key}: {text}" if text else f"    - {key}"
    if choices:
        line += f"。選択肢: {', '.join(choices)}"
    return line


def action_lines(actions):
    """The scripts run_action may start, as lines for its description."""
    lines = []
    for action in actions:
        head = f"- {action['object_id']}: {action['name']}"
        if action["description"]:
            head += f"。{' '.join(action['description'].split())}"
        lines.append(head)
        lines.extend(field_line(key, field) for key, field in action["fields"].items())
    return "\n".join(lines)


def run_action_description(actions):
    if not actions:
        return "家の機器の承認済みの操作を実行する。今は使える操作が無いので、このツールは呼ばない。"
    return (
        "家の機器を動かす（Home Assistant の script を実行する）。"
        "「電気つけて」のようにはっきり頼まれたときだけ使う。"
        "「暑いね」「まぶしいな」のようなつぶやきでは呼ばず、何をするか一言で提案して聞き返し、了承されてから呼ぶ。"
        "script には下の名前を、variables には下に並べた引数だけを入れる。実行の終わりは待たない。\n"
        f"使える操作:\n{action_lines(actions)}"
    )


def script_schema(actions):
    schema = {"type": "string", "description": "実行する操作の名前"}
    if actions:  # JSON Schema wants at least one value in an enum
        schema["enum"] = [action["object_id"] for action in actions]
    return schema


def registry(weather, calendar_events, calendar_add, run_action, call_service, home_states, home_history, actions=()):
    """The tools; `actions` (home.load_actions) is the scripts run_action may start."""
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
        Tool(
            name="run_action",
            description=run_action_description(actions),
            input_schema={
                "type": "object",
                "properties": {
                    "script": script_schema(actions),
                    "variables": {"type": "object", "description": "操作に渡す引数（その操作の引数だけ）"},
                },
                "required": ["script"],
            },
            handler=run_action,
        ),
        Tool(
            name="call_service",
            description=(
                "家の機器を Home Assistant の service で直接動かす。照明の明るさ・色、エアコンの温度など、"
                "run_action の操作に無いことをはっきり頼まれたときに使う。"
                "ただいま・いってきますのようなまとまった操作は、run_action にあればそちらを使う。"
                "entity_ids は先に home_states で調べた entity_id だけを入れ、推測で作らない。"
                "data の例: 照明（light.turn_on）は brightness_pct（0〜100）、"
                "color_temp_kelvin（暖かい色は 2700、白は 5000 前後）、rgb_color（[255, 0, 0] など）。"
                "実際に取れる範囲は home_states で確かめる。"
                "天井の電球は、明るさや色を変えると次に消すまで自動調整（Adaptive Lighting）から外れるので、そう一言添える。"
                "返るのは変わった機器の状態（1件1行、属性つき）。変わらなかったときはそう返る。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "service の domain。例: light"},
                    "service": {"type": "string", "description": "service の名前。例: turn_on"},
                    "entity_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "動かす entity_id（任意）",
                    },
                    "data": {"type": "object", "description": "service に渡す引数（任意）。entity_id は入れない"},
                },
                "required": ["domain", "service"],
            },
            handler=call_service,
        ),
        Tool(
            name="home_states",
            description=(
                "家の機器・センサーの今の状態を、1件1行（entity_id | 名前 | 状態 | 単位）で返す。"
                "部屋の温度・湿度、照明やエアコンの状態、窓を開けたほうがいいかなど、家の今の様子を聞かれたときに使う。"
                "domain（light, sensor, climate など）を渡すとその種類だけになる。"
                "名前は日本語と英語が混ざっているので、一覧から当てはまるものを選んで答える。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "domain": {"type": "string", "description": "絞り込む domain（任意）。例: sensor"},
                },
            },
            handler=home_states,
        ),
        Tool(
            name="home_history",
            description=(
                "家の機器・センサーの最近の履歴を、1時間ごとにまとめて返す。時刻は日本時間。"
                "数値は平均・最小・最大、数値でない状態はその時間の最後の値。変化の無かった時間は行が無い（前の値のまま）。"
                "今日どれくらい働いたか、寝られたか、部屋の温度がどう変わったかなど、最近の様子を聞かれたときに使う。"
                "entity_id は先に home_states で調べる。"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "entity_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "読む entity_id",
                    },
                    "hours": {"type": "integer", "minimum": 1, "maximum": 168, "description": "何時間前から（既定 24）"},
                },
                "required": ["entity_ids"],
            },
            handler=home_history,
        ),
    ]
