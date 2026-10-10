"""Ask Home Assistant's conversation API whether a sentence is one of its voice commands,
read the home's weather from HA for the weather tool, start the dance's light
show (home/packages/dance_lights.yaml), and back the home tools: run_action (the
scripts labelled `core`), call_service, home_states and home_history.

The rules (sentence triggers) and the replies live in HA, in
home/packages/voice_commands.yaml. The top of this module is stdlib only; the
HA client (home/ha.py reads config.json at import) is imported when asked.
"""

import asyncio
import fnmatch
import json
import logging
import math
import re
import sys
import urllib.parse
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


def start_script(entity_id):
    # script.turn_on returns once the script has started, not when it ends.
    rest("POST", "/api/services/script/turn_on", {"entity_id": entity_id})


async def run_script(entity_id):
    """Start an HA script. Never raises: the dance goes on when HA is down."""
    try:
        await asyncio.to_thread(start_script, entity_id)
    except Exception as e:
        log.warning("%s failed: %s: %s", entity_id, type(e).__name__, e)


async def dance_lights_blackout():
    await run_script("script.dance_lights_blackout")


async def dance_lights_start():
    await run_script("script.dance_lights")


async def dance_lights_end():
    await run_script("script.dance_lights_end")


# A script core may run (run_action) carries this HA label.
ACTION_LABEL = "core"
HISTORY_HOURS = (1, 168)


def fetch_actions():
    """The labelled scripts as {object_id, name, description, fields}, sorted by object_id."""
    rendered = rest("POST", "/api/template", {"template": f"{{{{ label_entities('{ACTION_LABEL}') | tojson }}}}"})
    entity_ids = json.loads(rendered)
    services = next((d["services"] for d in json.loads(rest("GET", "/api/services")) if d["domain"] == "script"), {})
    actions = []
    for entity_id in sorted(entity_ids):
        if not entity_id.startswith("script."):
            continue
        object_id = entity_id.removeprefix("script.")
        service = services.get(object_id, {})
        actions.append(
            {
                "object_id": object_id,
                "name": service.get("name") or object_id,
                "description": service.get("description") or "",
                "fields": service.get("fields") or {},
            }
        )
    return actions


async def load_actions():
    """The scripts run_action may start, read once at startup; [] when HA cannot say."""
    try:
        actions = await asyncio.to_thread(fetch_actions)
    except Exception as e:
        log.warning("reading the %r scripts failed, no actions: %s: %s", ACTION_LABEL, type(e).__name__, e)
        return []
    log.info("actions: %s", ", ".join(a["object_id"] for a in actions) or "none")
    return actions


def check_action(actions, args):
    """(entity_id, variables) to start, or the text that refuses the request."""
    by_id = {a["object_id"]: a for a in actions}
    name = args.get("script")
    if name not in by_id:
        return f"{name} は使える操作にありません。使えるのは {', '.join(by_id) or 'なし'} です。"
    variables = args.get("variables") or {}
    if not isinstance(variables, dict):
        return "variables はオブジェクトで渡してください。"
    unknown = sorted(set(variables) - set(by_id[name]["fields"]))
    if unknown:
        return f"{name} は {', '.join(unknown)} を受け付けません。"
    return f"script.{name}", variables


async def run_action(actions, args):
    """The run_action tool's handler: start an approved script without waiting for it. Never raises."""
    checked = check_action(actions, args)
    if isinstance(checked, str):
        return checked
    entity_id, variables = checked
    try:
        await asyncio.to_thread(
            rest, "POST", "/api/services/script/turn_on", {"entity_id": entity_id, "variables": variables}
        )
    except Exception as e:
        log.warning("%s failed: %s: %s", entity_id, type(e).__name__, e)
        return f"{args['script']} を実行できませんでした。"
    return f"{args['script']} を実行しました。"


def denied(entity_id, denylist):
    return any(fnmatch.fnmatchcase(entity_id, pattern) for pattern in denylist)


def state_line(s, attributes=()):
    """entity_id | friendly_name | state | unit, then those of `attributes` the entity has."""
    attrs = s.get("attributes", {})
    name, unit = attrs.get("friendly_name", ""), attrs.get("unit_of_measurement", "")
    line = f"{s['entity_id']} | {name} | {s['state']} | {unit}"
    extra = [f"{key}={json.dumps(attrs[key], ensure_ascii=False)}" for key in attributes if attrs.get(key) is not None]
    return f"{line} | {' '.join(extra)}" if extra else line


def format_states(states, denylist, domain=None):
    """One line per entity: entity_id | friendly_name | state | unit."""
    lines = []
    for s in sorted(states, key=lambda s: s["entity_id"]):
        entity_id = s["entity_id"]
        if denied(entity_id, denylist) or (domain and not entity_id.startswith(f"{domain}.")):
            continue
        lines.append(state_line(s))
    return "\n".join(lines) or "該当する entity がありません。"


async def home_states(denylist, args):
    """The home_states tool's handler. Never raises."""
    try:
        states = json.loads(await asyncio.to_thread(rest, "GET", "/api/states"))
    except Exception as e:
        log.warning("home_states failed: %s: %s", type(e).__name__, e)
        return "家の状態を取得できませんでした。"
    return format_states(states, denylist, args.get("domain") or None)


# The attributes call_service shows of a changed state, so the model can tell what it did.
CHANGED_ATTRIBUTES = (
    "brightness",
    "color_mode",
    "color_temp_kelvin",
    "rgb_color",
    "hs_color",
    "temperature",
    "hvac_mode",
    "fan_mode",
    "volume_level",
)
NAME = re.compile(r"[a-z0-9_]+")
ENTITY_ID = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
# Other targets (an area, a device, entity_id "all") could reach a denylisted entity.
TARGET_KEYS = ("entity_id", "device_id", "area_id", "floor_id", "label_id")


def check_service(service_denylist, denylist, args):
    """(path, body) to POST, or the text that refuses the request."""
    domain, service = args.get("domain"), args.get("service")
    if not all(isinstance(n, str) and NAME.fullmatch(n) for n in (domain, service)):
        return "domain と service は英小文字・数字・_ の名前で渡してください。"
    if denied(f"{domain}.{service}", service_denylist):
        return f"{domain}.{service} は呼べません。"
    entity_ids = args.get("entity_ids") or []
    if not isinstance(entity_ids, list) or not all(isinstance(e, str) and ENTITY_ID.fullmatch(e) for e in entity_ids):
        return "entity_ids は entity_id の配列で渡してください。"
    refused = [e for e in entity_ids if denied(e, denylist)]
    if refused:
        return f"{', '.join(refused)} は動かせません。"
    data = args.get("data") or {}
    if not isinstance(data, dict):
        return "data はオブジェクトで渡してください。"
    targets = [key for key in TARGET_KEYS if key in data]
    if targets:
        return f"data に {', '.join(targets)} は入れず、対象は entity_ids で渡してください。"
    body = dict(data, entity_id=entity_ids) if entity_ids else dict(data)
    return f"/api/services/{domain}/{service}", body


def format_changed(states, denylist):
    """The states a service call changed, one line each with the CHANGED_ATTRIBUTES it has."""
    lines = [
        state_line(s, CHANGED_ATTRIBUTES)
        for s in sorted(states, key=lambda s: s["entity_id"])
        if not denied(s["entity_id"], denylist)
    ]
    return "\n".join(lines) or "呼びましたが、変わった状態はありません。"


async def call_service(service_denylist, denylist, args):
    """The call_service tool's handler: call an HA service, then show what changed. Never raises."""
    checked = check_service(service_denylist, denylist, args)
    if isinstance(checked, str):
        return checked
    path, body = checked
    name = f"{args['domain']}.{args['service']}"
    try:
        # Without ?return_response, HA answers with the states that changed during the call.
        states = json.loads(await asyncio.to_thread(rest, "POST", path, body))
    except Exception as e:
        log.warning("%s failed: %s: %s", name, type(e).__name__, e)
        return f"{name} を呼べませんでした。"
    return format_changed(states, denylist)


def number(state):
    try:
        value = float(state)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def summarize_history(series):
    """Each entity's changes per JST hour: numbers as avg/min/max, other states as the hour's last."""
    blocks = []
    for changes in series:
        if not changes:
            continue
        # minimal_response puts entity_id on the first change only.
        lines = [changes[0]["entity_id"]]
        hours = {}
        for change in changes:
            at = datetime.fromisoformat(change["last_changed"]).astimezone(JST)
            hours.setdefault(at.strftime("%m-%d %H:00"), []).append(change["state"])
        for hour, values in hours.items():
            numbers = [n for n in map(number, values) if n is not None]
            if numbers:
                avg = sum(numbers) / len(numbers)
                lines.append(f"{hour} avg {avg:.4g} min {min(numbers):.4g} max {max(numbers):.4g}")
            else:
                lines.append(f"{hour} {values[-1]}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) or "履歴がありません。"


def fetch_history(entity_ids, hours):
    start = datetime.now(timezone.utc) - timedelta(hours=hours)
    path = (
        f"/api/history/period/{urllib.parse.quote(start.isoformat())}"
        f"?filter_entity_id={','.join(entity_ids)}&minimal_response&no_attributes"
    )
    return json.loads(rest("GET", path))


async def home_history(denylist, args):
    """The home_history tool's handler. Never raises."""
    entity_ids = args.get("entity_ids")
    hours = args.get("hours", 24)
    if not isinstance(entity_ids, list) or not entity_ids or not all(isinstance(e, str) for e in entity_ids):
        return "entity_ids を1つ以上渡してください。"
    low, high = HISTORY_HOURS
    if isinstance(hours, bool) or not isinstance(hours, int) or not low <= hours <= high:
        return f"hours は {low}〜{high} の整数で渡してください。"
    refused = [e for e in entity_ids if denied(e, denylist)]
    if refused:
        return f"{', '.join(refused)} は読めません。"
    try:
        series = await asyncio.to_thread(fetch_history, entity_ids, hours)
    except Exception as e:
        log.warning("home_history failed: %s: %s", type(e).__name__, e)
        return "履歴を取得できませんでした。"
    return summarize_history(series)
