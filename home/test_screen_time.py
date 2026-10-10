from datetime import datetime, timedelta

import screen_time as st
from ha import JST

START = datetime(2026, 10, 10, 4, 0, tzinfo=JST)


def at(hh: int, mm: int, ss: int = 0) -> datetime:
    return START.replace(hour=hh, minute=mm, second=ss)


def test_day_start_before_and_after_4am():
    assert st.day_start(datetime(2026, 10, 10, 3, 59, tzinfo=JST)) == datetime(2026, 10, 9, 4, 0, tzinfo=JST)
    assert st.day_start(datetime(2026, 10, 10, 4, 0, tzinfo=JST)) == START
    assert st.day_start(datetime(2026, 10, 10, 23, 0, tzinfo=JST)) == START


def test_app_name():
    assert st.app_name("com.mitchellh.ghostty") == "Ghostty"
    assert st.app_name("google-chrome") == "Chrome"
    assert st.app_name("org.mozilla.firefox") == "firefox"


def test_counts_foreground_time_per_app():
    events = [
        (at(9, 0), st.APP, "emacs"),
        (at(9, 30), st.APP, "google-chrome"),
        (at(9, 40), st.APP, "emacs"),
    ]
    totals = st.per_app(events, START, at(10, 0))
    assert totals == {"Emacs": 50 * 60, "Chrome": 10 * 60}


def test_idle_none_and_power_off_are_not_counted():
    events = [
        (at(9, 0), st.APP, "emacs"),
        (at(9, 10), st.IDLE, "on"),
        (at(9, 20), st.IDLE, "off"),
        (at(9, 30), st.APP, "none"),
        (at(9, 40), st.APP, "emacs"),
        (at(9, 45), st.POWER, "Powered Off"),
        (at(11, 0), st.POWER, "Powered On"),
        (at(11, 5), st.APP, "unavailable"),
    ]
    totals = st.per_app(events, START, at(12, 0))
    # 9:00-9:10, 9:20-9:30, 9:40-9:45, 11:00-11:05
    assert totals == {"Emacs": 30 * 60}


def test_state_before_start_carries_in_and_is_clipped():
    events = [(START - timedelta(hours=2), st.APP, "emacs")]
    assert st.per_app(events, START, at(4, 10)) == {"Emacs": 10 * 60}


def test_report_ranks_top_apps():
    totals = {f"app{i}": (i + 1) * 60.0 for i in range(7)}
    r = st.report(totals, START)
    assert r["minutes"] == sum(range(1, 8))
    assert r["most_used"] == {"app": "app6", "minutes": 7}
    assert [a["app"] for a in r["top_apps"]] == ["app6", "app5", "app4", "app3", "app2"]


def test_report_empty_day():
    r = st.report({}, START)
    assert r["minutes"] == 0 and r["most_used"] is None and r["top_apps"] == []
