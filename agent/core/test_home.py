import asyncio
import json
from pathlib import Path

import pytest

import home


def body(response_type, speech=""):
    return {
        "response": {
            "response_type": response_type,
            "speech": {"plain": {"speech": speech}},
            "data": {},
        },
        "conversation_id": None,
    }


def test_matched_sentence_gives_the_reply():
    assert home.parse(body("action_done", "間接照明つけます")) == "間接照明つけます"


def test_error_gives_none():
    assert home.parse(body("error", "すみません、わかりませんでした")) is None


class FakeHA:
    """Stands in for home.rest: answers by path prefix and records every call."""

    def __init__(self, answers):
        self.answers = answers  # path prefix -> JSON-able body, or an exception to raise
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        for prefix, answer in self.answers.items():
            if path.startswith(prefix):
                if isinstance(answer, Exception):
                    raise answer
                return json.dumps(answer).encode()
        raise AssertionError(f"unexpected {method} {path}")


SERVICES = [
    {"domain": "light", "services": {"turn_on": {"name": "Turn on"}}},
    {
        "domain": "script",
        "services": {
            "lights": {
                "name": "照明",
                "description": "照明をつける・消す。",
                "fields": {"target": {"name": "対象"}, "on": {"name": "点けるか"}},
            },
            "tadaima": {"name": "ただいま", "fields": {}},
            "dance_lights": {"name": "Dance Lights"},
        },
    },
]


def test_fetch_actions_takes_the_labelled_scripts_with_their_fields(monkeypatch):
    labelled = ["script.tadaima", "light.indirect_light", "script.lights"]
    ha = FakeHA({"/api/template": labelled, "/api/services": SERVICES})
    monkeypatch.setattr(home, "rest", ha)
    assert home.fetch_actions() == [
        {
            "object_id": "lights",
            "name": "照明",
            "description": "照明をつける・消す。",
            "fields": {"target": {"name": "対象"}, "on": {"name": "点けるか"}},
        },
        {"object_id": "tadaima", "name": "ただいま", "description": "", "fields": {}},
    ]
    assert "label_entities('core')" in ha.calls[0][2]["template"]


def test_load_actions_failure_gives_no_actions(monkeypatch):
    for error in (OSError("refused"), TimeoutError("slow"), RuntimeError("no token")):
        monkeypatch.setattr(home, "rest", FakeHA({"/api/template": error}))
        assert asyncio.run(home.load_actions()) == []


ACTIONS = [
    {"object_id": "lights", "name": "照明", "description": "", "fields": {"target": {}, "on": {}}},
    {"object_id": "tadaima", "name": "ただいま", "description": "", "fields": {}},
]


@pytest.mark.parametrize(
    "args",
    [
        {"script": "dance_lights"},
        {"script": "lights", "variables": {"target": "all", "brightness": 50}},
        {"script": "tadaima", "variables": {"x": 1}},
        {"script": "lights", "variables": "all"},
    ],
)
def test_run_action_refuses_without_calling_ha(monkeypatch, args):
    ha = FakeHA({})
    monkeypatch.setattr(home, "rest", ha)
    reply = asyncio.run(home.run_action(ACTIONS, args))
    assert "実行しました" not in reply
    assert ha.calls == []


def test_run_action_starts_the_script_with_its_variables(monkeypatch):
    ha = FakeHA({"/api/services/script/turn_on": []})
    monkeypatch.setattr(home, "rest", ha)
    args = {"script": "lights", "variables": {"target": "all", "on": True}}
    assert asyncio.run(home.run_action(ACTIONS, args)) == "lights を実行しました。"
    assert ha.calls == [
        (
            "POST",
            "/api/services/script/turn_on",
            {"entity_id": "script.lights", "variables": {"target": "all", "on": True}},
        )
    ]


def test_run_action_failure_gives_text(monkeypatch):
    monkeypatch.setattr(home, "rest", FakeHA({"/api/services/script/turn_on": OSError("refused")}))
    assert asyncio.run(home.run_action(ACTIONS, {"script": "tadaima"})) == "tadaima を実行できませんでした。"


DENYLIST = ("sensor.*_active_window_title", "sensor.backup_*")
STATES = [
    {
        "entity_id": "sensor.room_temperature",
        "state": "24.5",
        "attributes": {"friendly_name": "室温", "unit_of_measurement": "°C"},
    },
    {"entity_id": "sensor.pc_active_window_title", "state": "secret", "attributes": {"friendly_name": "PC Window"}},
    {"entity_id": "sensor.backup_state", "state": "idle", "attributes": {}},
    {"entity_id": "light.indirect_light", "state": "on", "attributes": {"friendly_name": "間接照明"}},
]


def test_home_states_gives_one_line_per_entity_without_the_denylist(monkeypatch):
    monkeypatch.setattr(home, "rest", FakeHA({"/api/states": STATES}))
    assert asyncio.run(home.home_states(DENYLIST, {})).splitlines() == [
        "light.indirect_light | 間接照明 | on | ",
        "sensor.room_temperature | 室温 | 24.5 | °C",
    ]


def test_home_states_narrows_to_a_domain(monkeypatch):
    monkeypatch.setattr(home, "rest", FakeHA({"/api/states": STATES}))
    assert asyncio.run(home.home_states(DENYLIST, {"domain": "light"})) == "light.indirect_light | 間接照明 | on | "


def test_home_states_failure_gives_text(monkeypatch):
    monkeypatch.setattr(home, "rest", FakeHA({"/api/states": OSError("refused")}))
    assert asyncio.run(home.home_states(DENYLIST, {})) == "家の状態を取得できませんでした。"


# minimal_response puts entity_id on the first change only. Times are UTC; 03:xx is 12:xx in JST.
HISTORY = [
    [
        {"entity_id": "sensor.room_temperature", "state": "20.0", "last_changed": "2026-10-10T03:00:00+00:00"},
        {"state": "22.0", "last_changed": "2026-10-10T03:20:00+00:00"},
        {"state": "unavailable", "last_changed": "2026-10-10T03:30:00+00:00"},
        {"state": "24.0", "last_changed": "2026-10-10T03:40:00+00:00"},
        {"state": "25.5", "last_changed": "2026-10-10T04:10:00+00:00"},
    ],
    [
        {"entity_id": "light.indirect_light", "state": "off", "last_changed": "2026-10-10T03:00:00+00:00"},
        {"state": "on", "last_changed": "2026-10-10T03:50:00+00:00"},
        {"state": "off", "last_changed": "2026-10-10T04:05:00+00:00"},
    ],
]


def test_home_history_sums_up_each_hour_in_jst(monkeypatch):
    ha = FakeHA({"/api/history/period/": HISTORY})
    monkeypatch.setattr(home, "rest", ha)
    args = {"entity_ids": ["sensor.room_temperature", "light.indirect_light"], "hours": 3}
    assert asyncio.run(home.home_history(DENYLIST, args)) == "\n".join(
        [
            "sensor.room_temperature",
            "10-10 12:00 avg 22 min 20 max 24",
            "10-10 13:00 avg 25.5 min 25.5 max 25.5",
            "",
            "light.indirect_light",
            "10-10 12:00 on",
            "10-10 13:00 off",
        ]
    )
    path = ha.calls[0][1]
    assert "filter_entity_id=sensor.room_temperature,light.indirect_light" in path
    assert path.endswith("&minimal_response&no_attributes")


@pytest.mark.parametrize(
    "args",
    [
        {"entity_ids": ["sensor.pc_active_window_title"], "hours": 24},
        {"entity_ids": ["sensor.room_temperature", "sensor.backup_state"]},
        {"entity_ids": ["sensor.room_temperature"], "hours": 0},
        {"entity_ids": ["sensor.room_temperature"], "hours": 169},
        {"entity_ids": ["sensor.room_temperature"], "hours": 2.5},
        {"entity_ids": []},
        {"entity_ids": "sensor.room_temperature"},
    ],
)
def test_home_history_refuses_without_calling_ha(monkeypatch, args):
    ha = FakeHA({})
    monkeypatch.setattr(home, "rest", ha)
    assert asyncio.run(home.home_history(DENYLIST, args))
    assert ha.calls == []


def test_home_history_failure_gives_text(monkeypatch):
    monkeypatch.setattr(home, "rest", FakeHA({"/api/history/period/": OSError("refused")}))
    assert asyncio.run(home.home_history(DENYLIST, {"entity_ids": ["sensor.x"]})) == "履歴を取得できませんでした。"


PACKAGES = Path(__file__).resolve().parents[2] / "home" / "packages"


@pytest.mark.parametrize("name", ["lights.yaml", "voice_commands.yaml"])
def test_packages_are_yaml(name):
    yaml = pytest.importorskip("yaml")
    assert yaml.safe_load((PACKAGES / name).read_text(encoding="utf-8"))


def test_lights_script_has_target_and_on_fields():
    yaml = pytest.importorskip("yaml")
    script = yaml.safe_load((PACKAGES / "lights.yaml").read_text(encoding="utf-8"))["script"]["lights"]
    # An unquoted `on` key loads as True.
    assert set(script["fields"]) == {"target", "on"}
    options = script["fields"]["target"]["selector"]["select"]["options"]
    assert [o["value"] for o in options] == ["indirect", "ceiling", "all"]
