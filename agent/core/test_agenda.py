import asyncio
import json
from urllib.parse import parse_qs, urlparse

import agenda
import home

ENTITY = "calendar.yotei"
# Shaped like HA's /api/calendars answer for 2026-10-12 (Mon) to 10-18.
EVENTS = [
    {
        "start": {"dateTime": "2026-10-11T23:00:00+09:00"},
        "end": {"dateTime": "2026-10-12T05:00:00+09:00"},
        "summary": "クラブ",
        "location": "ZEROTOKYO",
    },
    {"start": {"date": "2026-10-13"}, "end": {"date": "2026-10-16"}, "summary": "Stay at ホテル"},
    {"start": {"date": "2026-10-13"}, "end": {"date": "2026-10-16"}, "summary": ""},
    {"start": {"date": "2026-10-17"}, "end": {"date": "2026-10-18"}, "summary": "休み"},
    {
        "start": {"dateTime": "2026-10-13T03:20:00+00:00"},
        "end": {"dateTime": "2026-10-13T05:00:00+00:00"},
        "summary": "SKY713",
    },
]


def test_events_are_jst_with_weekdays_and_inclusive_last_days(monkeypatch):
    asked = []

    def fake_rest(method, path, payload=None):
        asked.append(path)
        return json.dumps(EVENTS).encode()

    monkeypatch.setattr(home, "rest", fake_rest)
    result = json.loads(asyncio.run(agenda.events(ENTITY, {"start_date": "2026-10-12", "days": 7})))
    url = urlparse(asked[0])
    assert url.path == "/api/calendars/calendar.yotei"
    assert parse_qs(url.query) == {"start": ["2026-10-12T00:00:00+09:00"], "end": ["2026-10-19T00:00:00+09:00"]}
    assert result == {
        "range": "10-12(月)〜10-18(日)",
        "events": [
            {
                "summary": "クラブ",
                "location": "ZEROTOKYO",
                "start": "10-11(日) 23:00",
                "end": "10-12(月) 05:00",
                "began_before_range": True,
            },
            {"summary": "Stay at ホテル", "all_day": True, "first_day": "10-13(火)", "last_day": "10-15(木)"},
            {"summary": "休み", "all_day": True, "first_day": "10-17(土)"},
            {"summary": "SKY713", "start": "10-13(火) 12:20", "end": "10-13(火) 14:00"},
        ],
    }


def test_days_defaults_to_one(monkeypatch):
    asked = []
    monkeypatch.setattr(home, "rest", lambda method, path, payload=None: asked.append(path) or b"[]")
    result = json.loads(asyncio.run(agenda.events(ENTITY, {"start_date": "2026-10-11"})))
    assert parse_qs(urlparse(asked[0]).query)["end"] == ["2026-10-12T00:00:00+09:00"]
    assert result == {"range": "10-11(日)〜10-11(日)", "events": []}


def test_timed_event_data_defaults_to_an_hour():
    assert agenda.event_data(ENTITY, {"summary": "歯医者", "start": "2026-10-20T15:00", "location": "駅前"}) == {
        "entity_id": ENTITY,
        "summary": "歯医者",
        "location": "駅前",
        "start_date_time": "2026-10-20 15:00:00",
        "end_date_time": "2026-10-20 16:00:00",
    }


def test_all_day_event_data_ends_the_day_after_the_last():
    data = agenda.event_data(ENTITY, {"summary": "旅行", "start": "2026-10-20", "end": "2026-10-22"})
    assert (data["start_date"], data["end_date"]) == ("2026-10-20", "2026-10-23")
    one_day = agenda.event_data(ENTITY, {"summary": "休み", "start": "2026-10-20"})
    assert (one_day["start_date"], one_day["end_date"]) == ("2026-10-20", "2026-10-21")


def test_add_posts_create_event(monkeypatch):
    posted = []
    monkeypatch.setattr(home, "rest", lambda method, path, payload=None: posted.append((method, path, payload)) or b"[]")
    args = {"summary": "歯医者", "start": "2026-10-20T15:00", "end": "2026-10-20T15:30"}
    assert asyncio.run(agenda.add(ENTITY, args)) == "追加しました。"
    assert posted == [("POST", "/api/services/calendar/create_event", agenda.event_data(ENTITY, args))]


def test_failures_give_text_instead_of_raising(monkeypatch):
    def broken_rest(method, path, payload=None):
        raise RuntimeError("no token")

    monkeypatch.setattr(home, "rest", broken_rest)
    assert asyncio.run(agenda.events(ENTITY, {"start_date": "2026-10-12"})) == agenda.EVENTS_FAILED
    assert asyncio.run(agenda.add(ENTITY, {"summary": "x", "start": "2026-10-20"})) == agenda.ADD_FAILED
