import asyncio
import logging
import sys
from datetime import datetime

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

    class UserMessage:
        def __init__(self, content):
            self.content = content

    class ToolUseBlock:
        def __init__(self, name, input):
            self.name = name
            self.input = input

    class ToolResultBlock:
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
        yield FakeSDK.AssistantMessage("sonnet", [FakeSDK.ToolUseBlock("weather", {"place": "東京"})])
        yield FakeSDK.UserMessage([FakeSDK.ToolResultBlock([{"type": "text", "text": "晴れ\n20度"}])])
        yield FakeSDK.UserMessage("plain text")
        yield FakeSDK.ResultMessage("晴れだよ")


class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 10, 15, 4, tzinfo=brain.JST).astimezone(tz)


def test_stamp_has_the_date_weekday_and_time():
    assert brain.stamp(datetime(2026, 10, 12, 7, 5, tzinfo=brain.JST)) == "[2026-10-12(月) 07:05]"


def test_claude_gets_the_date_and_the_log_keeps_the_original(monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="brain")
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
    # What the stage's screen gets: the prompt, the tool call and result, the end.
    assert [(r.log_kind, r.getMessage()) for r in caplog.records if hasattr(r, "log_kind")] == [
        ("claude_in", "[2026-10-10(土) 15:04] ミク、明日の天気は"),
        ("tool", 'weather {"place": "東京"}'),
        ("tool", "-> 晴れ 20度"),
        ("done", "sonnet 0.0s in 1 out 0"),
    ]


def test_only_a_wake_word_goes_straight_to_claude(monkeypatch):
    async def ask_home(text):
        raise AssertionError("nothing to ask")

    events, claude, _ = run(ask_home, "サル", monkeypatch)
    assert events == CLAUDE_EVENTS
    assert claude.calls == ["サル"]


def test_result_head_joins_text_blocks_on_one_line():
    content = [{"type": "text", "text": "晴れ\n気温 20度"}, {"type": "image"}, {"type": "text", "text": "風 弱い"}]
    assert brain.result_head(content) == "晴れ 気温 20度 風 弱い"


def test_result_head_handles_str_and_none():
    assert brain.result_head("a\n\nb") == "a b"
    assert brain.result_head(None) == ""


def test_result_head_cuts_long_text():
    assert brain.result_head("あ" * 10, limit=4) == "ああああ…"
    assert brain.result_head("あ" * 4, limit=4) == "ああああ"


def test_done_line():
    usage = {"input_tokens": 1000, "cache_read_input_tokens": 234, "output_tokens": 56}
    assert brain.done_line("sonnet-4", 3200, usage) == "sonnet-4 3.2s in 1234 out 56"
    assert brain.done_line(None, None, {}) == "None 0.0s in 0 out 0"
