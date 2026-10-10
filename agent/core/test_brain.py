import asyncio

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


def test_only_a_wake_word_goes_straight_to_claude(monkeypatch):
    async def ask_home(text):
        raise AssertionError("nothing to ask")

    events, claude, _ = run(ask_home, "サル", monkeypatch)
    assert events == CLAUDE_EVENTS
    assert claude.calls == ["サル"]
