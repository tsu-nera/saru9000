"""Read and add the events of one Google Calendar, through HA's calendar entity.

The Google Calendar integration and its OAuth live in HA; the entity is
config.json's calendar_entity. Times the model sees are JST, with the weekday.
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from urllib.parse import quote

import home
from brain import WEEKDAYS
from home import JST

log = logging.getLogger("agenda")

EVENTS_FAILED = "予定を取得できませんでした。"
ADD_FAILED = "予定を追加できませんでした。"
# Timed events without an end in the request last this long.
DEFAULT_DURATION = timedelta(hours=1)


def day_label(d):
    return f"{d:%m-%d}({WEEKDAYS[d.weekday()]})"


def time_label(t):
    return f"{day_label(t)} {t:%H:%M}"


def format_event(event, range_start):
    """One event for the model; None for an event without a title (Google makes some)."""
    summary = (event.get("summary") or "").strip()
    if not summary:
        return None
    item = {"summary": summary}
    if event.get("location"):
        item["location"] = event["location"]
    start, end = event["start"], event["end"]
    if "date" in start:
        first = date.fromisoformat(start["date"])
        # HA (and Google) give the day after the last one.
        last = date.fromisoformat(end["date"]) - timedelta(days=1)
        item["all_day"] = True
        item["first_day"] = day_label(first)
        if last != first:
            item["last_day"] = day_label(last)
        begins_before = first < range_start.date()
    else:
        begin = datetime.fromisoformat(start["dateTime"]).astimezone(JST)
        item["start"] = time_label(begin)
        item["end"] = time_label(datetime.fromisoformat(end["dateTime"]).astimezone(JST))
        begins_before = begin < range_start
    if begins_before:
        item["began_before_range"] = True
    return item


def format_events(events, range_start, range_end):
    items = [item for item in (format_event(e, range_start) for e in events) if item is not None]
    return json.dumps(
        {
            "range": f"{day_label(range_start)}〜{day_label(range_end - timedelta(days=1))}",
            "events": items,
        },
        ensure_ascii=False,
    )


def fetch_events(entity, start_date, days):
    start = datetime.combine(date.fromisoformat(start_date), datetime.min.time(), JST)
    end = start + timedelta(days=days)
    path = f"/api/calendars/{entity}?start={quote(start.isoformat())}&end={quote(end.isoformat())}"
    return format_events(json.loads(home.rest("GET", path)), start, end)


async def events(entity, args):
    """The calendar_events tool's handler. Never raises, so Claude can say it failed."""
    try:
        return await asyncio.to_thread(fetch_events, entity, args["start_date"], int(args.get("days", 1)))
    except Exception as e:
        log.warning("calendar_events failed: %s: %s", type(e).__name__, e)
        return EVENTS_FAILED


def event_data(entity, args):
    """calendar.create_event's service data. A date-only start is an all-day event."""
    data = {"entity_id": entity, "summary": args["summary"]}
    if args.get("location"):
        data["location"] = args["location"]
    start = args["start"]
    if "T" not in start:
        last = date.fromisoformat(args.get("end") or start)
        data["start_date"] = start
        data["end_date"] = (last + timedelta(days=1)).isoformat()
    else:
        begin = datetime.fromisoformat(start)
        finish = datetime.fromisoformat(args["end"]) if args.get("end") else begin + DEFAULT_DURATION
        data["start_date_time"] = begin.strftime("%Y-%m-%d %H:%M:%S")
        data["end_date_time"] = finish.strftime("%Y-%m-%d %H:%M:%S")
    return data


def create_event(entity, args):
    home.rest("POST", "/api/services/calendar/create_event", event_data(entity, args))


async def add(entity, args):
    """The calendar_add tool's handler. Never raises, so Claude can say it failed."""
    try:
        await asyncio.to_thread(create_event, entity, args)
        return "追加しました。"
    except Exception as e:
        log.warning("calendar_add failed: %s: %s", type(e).__name__, e)
        return ADD_FAILED
