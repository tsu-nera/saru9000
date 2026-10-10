import asyncio
import json
from datetime import datetime

import pytest

import brain
import home
import tools


async def nothing(args):
    return ""


NAMES = ["weather", "calendar_events", "calendar_add", "run_action", "home_states", "home_history"]
ALLOWED = [f"mcp__core__{name}" for name in NAMES]

# Shaped like home.fetch_actions (the fields come from HA's /api/services).
ACTIONS = [
    {
        "object_id": "lights",
        "name": "照明",
        "description": "照明をつける・消す。",
        "fields": {
            "target": {
                "name": "対象",
                "description": "どの照明か",
                "selector": {
                    "select": {
                        "options": [
                            {"label": "間接照明", "value": "indirect"},
                            {"label": "天井の電球", "value": "ceiling"},
                            {"label": "全部", "value": "all"},
                        ]
                    }
                },
            },
            "on": {"name": "点けるか", "selector": {"boolean": {}}},
        },
    },
    {"object_id": "tadaima", "name": "ただいま", "description": "", "fields": {}},
]


def registry(actions=()):
    return tools.registry(
        weather=nothing,
        calendar_events=nothing,
        calendar_add=nothing,
        run_action=nothing,
        home_states=nothing,
        home_history=nothing,
        actions=actions,
    )


def test_registry_has_weather_calendar_and_home():
    assert [tool.name for tool in registry()] == NAMES
    assert all(tool.handler is nothing for tool in registry())


def test_run_action_description_lists_the_scripts():
    tool = next(t for t in registry(ACTIONS) if t.name == "run_action")
    for text in ("lights: 照明。照明をつける・消す。", "target: 対象、どの照明か", "indirect（間接照明）", "all（全部）"):
        assert text in tool.description
    assert "on: 点けるか。選択肢: true, false" in tool.description
    assert "tadaima: ただいま" in tool.description
    assert "はっきり頼まれたときだけ" in tool.description
    assert tool.input_schema["properties"]["script"]["enum"] == ["lights", "tadaima"]


def test_registry_without_actions_still_has_run_action():
    tool = next(t for t in registry() if t.name == "run_action")
    assert "使える操作が無い" in tool.description
    assert "enum" not in tool.input_schema["properties"]["script"]


def test_claude_options_allow_only_the_registry_and_no_builtin_tools():
    fields = brain.option_fields("sonnet", registry(), "system prompt")
    assert fields["allowed_tools"] == ALLOWED
    assert fields["tools"] == []
    assert fields["strict_mcp_config"] is True
    assert fields["env"] == brain.ISOLATION_ENV


def test_claude_options_carry_the_registry_as_an_mcp_server():
    pytest.importorskip("claude_agent_sdk")
    options = brain.build_options("sonnet", "system prompt", registry())
    assert list(options.mcp_servers) == ["core"]
    assert options.allowed_tools == ALLOWED
    assert options.tools == []


# Shaped like HA's answers (met.no forecasts are in UTC).
STATES = {
    "/api/states/sensor.rainfall_now": {"entity_id": "sensor.rainfall_now", "state": "0.0"},
    "/api/states/sensor.rainfall_next_hour_max": {"entity_id": "sensor.rainfall_next_hour_max", "state": "1.25"},
    "/api/states/sensor.rain_starts_in": {"entity_id": "sensor.rain_starts_in", "state": "35"},
}
HOURLY = [
    {
        "datetime": "2026-10-10T06:00:00+00:00",
        "condition": "cloudy",
        "temperature": 21.3,
        "precipitation": 0.0,
        "humidity": 70,
        "wind_speed": 9.4,
        "wind_bearing": 180.0,
        "cloud_coverage": 90.0,
        "uv_index": 1.2,
    },
]
DAILY = [
    {
        "datetime": "2026-10-10T15:00:00+00:00",
        "condition": "clear-night",
        "temperature": 23.0,
        "templow": 14.1,
        "precipitation": 0.0,
        "humidity": 60,
        "wind_speed": 8.0,
        "wind_bearing": 10.0,
    },
    {
        "datetime": "2026-10-11T15:00:00+00:00",
        "condition": "rainy",
        "temperature": 19.5,
        "templow": 15.0,
        "precipitation": 4.2,
    },
]


def fake_rest(method, path, payload=None):
    if method == "GET":
        return json.dumps(STATES[path]).encode()
    assert path == "/api/services/weather/get_forecasts?return_response"
    forecast = {"hourly": HOURLY, "daily": DAILY}[payload["type"]]
    return json.dumps(
        {"changed_states": [], "service_response": {payload["entity_id"]: {"forecast": forecast}}}
    ).encode()


def test_weather_gives_jst_times_and_only_the_kept_fields(monkeypatch):
    monkeypatch.setattr(home, "rest", fake_rest)
    weather = json.loads(asyncio.run(home.weather({})))
    datetime.strptime(weather["now"], "%Y-%m-%d %H:%M")
    assert weather["rain"] == {"now_mm_h": "0.0", "next_hour_max_mm_h": "1.25", "starts_in_min": "35"}
    assert weather["hourly"] == [
        {
            "time": "10-10 15:00",
            "condition": "cloudy",
            "temperature": 21.3,
            "precipitation": 0.0,
            "humidity": 70,
            "wind_speed": 9.4,
        }
    ]
    assert weather["daily"] == [
        {
            "time": "10-11",
            "condition": "sunny",
            "temperature": 23.0,
            "templow": 14.1,
            "precipitation": 0.0,
            "humidity": 60,
            "wind_speed": 8.0,
        },
        {"time": "10-12", "condition": "rainy", "temperature": 19.5, "templow": 15.0, "precipitation": 4.2},
    ]


def test_hourly_keeps_clear_night():
    hourly = [{"datetime": "2026-10-10T13:00:00+00:00", "condition": "clear-night"}]
    assert home.forecast_entries(hourly, "%m-%d %H:%M", daily=False) == [
        {"time": "10-10 22:00", "condition": "clear-night"}
    ]


def test_weather_failure_gives_text_instead_of_raising(monkeypatch):
    for error in (OSError("refused"), TimeoutError("slow"), RuntimeError("no token"), KeyError("forecast")):

        def broken_rest(method, path, payload=None, error=error):
            raise error

        monkeypatch.setattr(home, "rest", broken_rest)
        assert asyncio.run(home.weather({})) == home.WEATHER_FAILED
