import asyncio
import logging
import sys
from datetime import datetime
from types import SimpleNamespace

import brain
from brain import Done, TextDelta

SARU = ["サル", "猿"]
CLAUDE_EVENTS = [TextDelta("こんにちは"), Done("sonnet", {"input_tokens": 1})]


class FakeClaude:
    def __init__(self):
        self.calls = []

    async def reply(self, text):
        self.calls.append(text)
        for event in CLAUDE_EVENTS:
            yield event


def run(ask_home, text, monkeypatch):
    logged = []
    monkeypatch.setattr(brain, "append_log", logged.append)
    claude = FakeClaude()
    wrapped = brain.HomeFirstBrain(claude, ask_home, SARU)

    async def collect():
        return [event async for event in wrapped.reply(text)]

    return asyncio.run(collect()), claude, logged


def test_matched_in_home_assistant_skips_claude(monkeypatch):
    async def ask_home(text):
        return "間接照明つけます"

    events, claude, logged = run(ask_home, "サル、間接照明つけて", monkeypatch)
    assert events == [TextDelta("間接照明つけます"), Done(brain.HOME_MODEL, {})]
    assert claude.calls == []
    assert logged[0]["model"] == brain.HOME_MODEL
    assert logged[0]["user"] == "サル、間接照明つけて"
    assert logged[0]["reply"] == "間接照明つけます"


def test_no_match_goes_to_claude_with_the_original_text(monkeypatch):
    async def ask_home(text):
        return None

    events, claude, logged = run(ask_home, "サル、今日の天気は", monkeypatch)
    assert events == CLAUDE_EVENTS
    assert claude.calls == ["サル、今日の天気は"]
    assert logged == []


def test_home_assistant_failure_goes_to_claude(monkeypatch):
    for error in (OSError("refused"), TimeoutError("slow"), RuntimeError("no token")):

        async def ask_home(text, error=error):
            raise error

        events, claude, _ = run(ask_home, "サル、間接照明つけて", monkeypatch)
        assert events == CLAUDE_EVENTS
        assert claude.calls == ["サル、間接照明つけて"]


def test_home_assistant_gets_the_text_without_wake_word_and_punctuation(monkeypatch):
    asked = []

    async def ask_home(text):
        asked.append(text)
        return None

    run(ask_home, "サル、間接照明つけて", monkeypatch)
    assert asked == ["間接照明つけて"]


class FakeSDK:
    """Stands in for claude_agent_sdk: only the message types ClaudeBrain.reply checks."""

    class StreamEvent:
        def __init__(self, event):
            self.event = event

    class AssistantMessage:
        def __init__(self, model, content=()):
            self.model = model
            self.content = list(content)

    class ToolUseBlock:
        def __init__(self, id, name, input):
            self.id = id
            self.name = name
            self.input = input

    class ToolResultBlock:
        def __init__(self, tool_use_id, content):
            self.tool_use_id = tool_use_id
            self.content = content

    class UserMessage:
        def __init__(self, content):
            self.content = content

    class ResultMessage:
        def __init__(self, result):
            self.result = result
            self.session_id = "s"
            self.duration_ms = 1
            self.usage = {"input_tokens": 1}


class FakeClient:
    def __init__(self):
        self.queries = []

    async def query(self, text):
        self.queries.append(text)

    async def receive_response(self):
        yield FakeSDK.StreamEvent({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "晴れだよ"}})
        yield FakeSDK.AssistantMessage("sonnet", [FakeSDK.ToolUseBlock("t1", "weather", {"place": "東京"})])
        yield FakeSDK.UserMessage([FakeSDK.ToolResultBlock("t1", [{"type": "text", "text": "晴れ" * 200}])])
        yield FakeSDK.ResultMessage("晴れだよ")


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 10, 15, 4, tzinfo=brain.JST).astimezone(tz)


def test_stamp_has_the_date_weekday_and_time():
    assert brain.stamp(datetime(2026, 10, 12, 7, 5, tzinfo=brain.JST)) == "[2026-10-12(月) 07:05]"


def test_claude_gets_the_date_and_the_log_keeps_the_original(monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", FakeSDK)
    monkeypatch.setattr(brain, "datetime", FixedDatetime)
    logged = []
    monkeypatch.setattr(brain, "append_log", logged.append)
    claude = brain.ClaudeBrain("system prompt")
    claude.client = FakeClient()

    async def collect():
        return [event async for event in claude.reply("ミク、明日の天気は")]

    events = asyncio.run(collect())
    assert claude.client.queries == ["[2026-10-10(土) 15:04] ミク、明日の天気は"]
    assert events == [TextDelta("晴れだよ"), Done("sonnet", {"input_tokens": 1})]
    assert logged[0]["user"] == "ミク、明日の天気は"


def test_only_a_wake_word_goes_straight_to_claude(monkeypatch):
    async def ask_home(text):
        raise AssertionError("nothing to ask")

    events, claude, _ = run(ask_home, "サル", monkeypatch)
    assert events == CLAUDE_EVENTS
    assert claude.calls == ["サル"]


def test_claude_brain_logs_the_query_tools_and_the_end_with_kinds(monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", FakeSDK)
    monkeypatch.setattr(brain, "datetime", FixedDatetime)
    monkeypatch.setattr(brain, "append_log", lambda record: None)
    claude = brain.ClaudeBrain("system prompt")
    claude.client = FakeClient()

    async def collect():
        return [event async for event in claude.reply("天気は")]

    with caplog.at_level(logging.INFO, logger="brain"):
        asyncio.run(collect())
    lines = [(r.kind, r.getMessage()) for r in caplog.records if hasattr(r, "kind")]
    assert [kind for kind, _ in lines] == ["claude_in", "tool", "tool", "done"]
    assert lines[0][1] == "[2026-10-10(土) 15:04] 天気は"
    assert lines[1][1] == 'weather {"place": "東京"}'
    assert lines[2][1].startswith("-> 晴れ晴れ") and len(lines[2][1]) == 3 + 200
    assert "sonnet" in lines[3][1] and "in 1 out 0" in lines[3][1]


def test_chat_log_keeps_each_tool_call_with_its_input_and_time(monkeypatch):
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", FakeSDK)
    monkeypatch.setattr(brain, "datetime", FixedDatetime)
    clock = iter([10.0, 10.25])
    # Only brain's clock: asyncio reads time.monotonic too.
    monkeypatch.setattr(brain, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    logged = []
    monkeypatch.setattr(brain, "append_log", logged.append)
    claude = brain.ClaudeBrain("system prompt")
    claude.client = FakeClient()

    async def collect():
        return [event async for event in claude.reply("天気は")]

    asyncio.run(collect())
    assert logged[0]["tools"] == [{"name": "weather", "input": {"place": "東京"}, "duration_ms": 250}]
