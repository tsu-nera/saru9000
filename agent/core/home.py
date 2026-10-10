"""Ask Home Assistant's conversation API whether a sentence is one of its voice commands,
and read the home's weather from HA for the weather tool.

The rules (sentence triggers) and the replies live in HA, in
home/packages/voice_commands.yaml. The top of this module is stdlib only; the
HA client (home/ha.py reads config.json at import) is imported when asked.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("home")

# The built-in rule-based agent: sentence triggers and HA's own intents, never an LLM.
AGENT_ID = "conversation.home_assistant"
# Seconds. HA answers in well under a second; this bounds a dead connection.
TIMEOUT = 10
HA_DIR = str(Path(__file__).resolve().parents[2] / "home")

JST = timezone(timedelta(hours=9))
WEATHER_ENTITY = "weather.forecast_zi_zhai"  # met.no
# Yahoo's rain radar (home/packages/rain.yaml), keyed by the name the model sees.
RAIN_SENSORS = {
    "now_mm_h": "sensor.rainfall_now",
    "next_hour_max_mm_h": "sensor.rainfall_next_hour_max",
    "starts_in_min": "sensor.rain_starts_in",
}
# The forecast fields the model gets; wind_bearing, cloud_coverage, uv_index, ... are dropped.
FORECAST_FIELDS = ("condition", "temperature", "templow", "precipitation", "humidity", "wind_speed")
WEATHER_FAILED = "天気を取得できませんでした。"


def parse(body):
    """The reply text of a conversation response, or None when HA understood nothing."""
    response = body["response"]
    if response.get("response_type") == "error":
        return None
    return response["speech"]["plain"]["speech"]


def rest(method, path, payload=None):
    if HA_DIR not in sys.path:
        sys.path.insert(0, HA_DIR)
    try:
        import ha

        return ha.rest(method, path, payload, TIMEOUT)
    except SystemExit as e:
        # ha.secret() exits when HA_TOKEN is missing; that must not stop the server.
        raise RuntimeError(f"home assistant is not configured: {e}") from e


def call_ha(text):
    payload = {"text": text, "language": "ja", "agent_id": AGENT_ID}
    return rest("POST", "/api/conversation/process", payload)


async def ask(text):
    """HA's reply to `text`, or None when no sentence trigger matched."""
    return parse(json.loads(await asyncio.to_thread(call_ha, text)))


def forecast_entries(entries, time_format, daily):
    """Forecast entries with JST times and only FORECAST_FIELDS."""
    result = []
    for entry in entries:
        time = datetime.fromisoformat(entry["datetime"]).astimezone(JST)
        item = {"time": time.strftime(time_format)}
        item.update({key: entry[key] for key in FORECAST_FIELDS if key in entry})
        # met.no puts the night's condition into some days.
        if daily and item.get("condition") == "clear-night":
            item["condition"] = "sunny"
        result.append(item)
    return result


def format_weather(now, rain, hourly, daily):
    """The weather tool's text: the rain sensors' states and both forecasts, as JSON."""
    return json.dumps(
        {
            "now": now.astimezone(JST).strftime("%Y-%m-%d %H:%M"),
            "rain": rain,
            "hourly": forecast_entries(hourly, "%m-%d %H:%M", daily=False),
            "daily": forecast_entries(daily, "%m-%d", daily=True),
        },
        ensure_ascii=False,
    )


def get_forecast(forecast_type):
    # get_forecasts returns a response, so ?return_response is required (400 without).
    # twice_daily is a 500 on met.no.
    body = rest(
        "POST",
        "/api/services/weather/get_forecasts?return_response",
        {"entity_id": WEATHER_ENTITY, "type": forecast_type},
    )
    return json.loads(body)["service_response"][WEATHER_ENTITY]["forecast"]


def fetch_weather():
    rain = {
        name: json.loads(rest("GET", f"/api/states/{entity}"))["state"]
        for name, entity in RAIN_SENSORS.items()
    }
    return format_weather(datetime.now(JST), rain, get_forecast("hourly"), get_forecast("daily"))


async def weather(args):
    """The weather tool's handler. Never raises, so Claude can say it could not get the weather."""
    try:
        return await asyncio.to_thread(fetch_weather)
    except Exception as e:
        log.warning("weather failed: %s: %s", type(e).__name__, e)
        return WEATHER_FAILED
