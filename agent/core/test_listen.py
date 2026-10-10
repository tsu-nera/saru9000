import asyncio

import listen

PAD = int(listen.PAD_SECONDS * listen.SAMPLE_RATE)
WIN = listen.VAD_WINDOW
PREROLL = int(listen.PREROLL_SECONDS * listen.SAMPLE_RATE)
# Silence (in windows) that ends a segment in the fake VAD.
END_WINDOWS = 3


class Segment:
    def __init__(self, samples, start):
        self.samples = samples
        self.start = start


class FakeVad:
    """Samples of 0.5 and up are speech; END_WINDOWS silent windows close a segment."""

    def __init__(self):
        self.received = []
        self.segments = []
        self.current = []
        self.silent = 0
        self.resets = 0
        self.position = 0
        self.start = 0

    def accept_waveform(self, samples):
        self.received.append(list(samples))
        if any(x >= 0.5 for x in samples):
            if not self.current:
                self.start = self.position
            self.current.extend(samples)
            self.silent = 0
        elif self.current:
            self.silent += 1
            if self.silent >= END_WINDOWS:
                self.close()
        self.position += len(samples)

    def close(self):
        self.segments.append(Segment(self.current, self.start))
        self.current = []
        self.silent = 0

    def flush(self):
        if self.current:
            self.close()

    def empty(self):
        return not self.segments

    @property
    def front(self):
        return self.segments[0]

    def pop(self):
        self.segments.pop(0)

    def reset(self):
        self.resets += 1
        self.position = 0
        self.segments = []
        self.current = []
        self.silent = 0


def speech(windows=2):
    return [0.5] * (WIN * windows)


def silence(windows=END_WINDOWS):
    return [0.0] * (WIN * windows)


def make(texts=None):
    vad = FakeVad()
    calls = []
    results = iter(texts or [])

    def recognize(samples):
        calls.append(list(samples))
        return next(results, "text")

    return listen.Listener(vad, recognize), vad, calls


def test_segment_is_padded_with_zeros_on_both_sides():
    listener, vad, calls = make(["こんにちは"])
    assert listener.feed(speech() + silence()) == ["こんにちは"]
    (samples,) = calls
    body = [0.5] * (WIN * 2)
    assert samples == [0.0] * PAD + body + [0.0] * PAD
    assert PAD == 4800


def test_audio_just_before_the_segment_goes_in_front_of_it():
    listener, vad, calls = make()
    # Quiet voice the fake VAD misses, like Silero's late onset.
    onset = [0.25] * (WIN * 20)
    listener.feed(onset + speech() + silence())
    (samples,) = calls
    assert samples == [0.0] * PAD + [0.25] * PREROLL + speech() + [0.0] * PAD


def test_audio_while_paused_never_reaches_vad_or_recognizer():
    listener, vad, calls = make(["after"])
    listener.pause()
    assert listener.feed(speech() + silence()) == []
    assert vad.received == []
    assert calls == []

    listener.resume()
    assert vad.resets == 1
    assert listener.feed(speech() + silence()) == ["after"]
    assert len(calls) == 1


def test_resume_drops_partial_window_buffered_before_pause():
    listener, vad, calls = make()
    listener.feed([0.5] * (WIN // 2))
    listener.pause()
    listener.resume()
    listener.feed([0.0] * WIN)
    assert vad.received == [[0.0] * WIN]


def test_empty_recognition_is_not_an_utterance():
    listener, vad, calls = make(["", "  ", "ok"])
    assert listener.feed(speech() + silence()) == []
    assert listener.feed(speech() + silence()) == []
    assert listener.feed(speech() + silence()) == ["ok"]
    assert len(calls) == 3


def test_flush_picks_up_trailing_segment():
    listener, vad, calls = make(["tail"])
    assert listener.feed(speech()) == []
    assert listener.flush() == ["tail"]


def test_partial_windows_are_buffered_across_feeds():
    listener, vad, calls = make()
    listener.feed([0.5] * (WIN - 1))
    assert vad.received == []
    listener.feed([0.5] * 2)
    assert [len(w) for w in vad.received] == [WIN]


def test_recognition_in_flight_across_pause_is_dropped():
    vad = FakeVad()
    holder = {}

    def recognize(samples):
        holder["listener"].pause()
        return "stale"

    listener = listen.Listener(vad, recognize)
    holder["listener"] = listener
    assert listener.feed(speech() + silence()) == []


def test_utterances_feeds_blocks_and_flushes():
    listener, vad, calls = make(["one", "two"])

    async def blocks():
        yield speech() + silence()
        yield speech()

    async def collect():
        return [t async for t in listen.utterances(listener, blocks())]

    assert asyncio.run(collect()) == ["one", "two"]


def test_pump_queues_texts():
    listener, vad, calls = make(["one"])

    async def blocks():
        yield speech() + silence()

    async def run():
        queue = asyncio.Queue()
        await listen.pump(listener, blocks(), queue)
        return queue.get_nowait()

    assert asyncio.run(run()) == "one"


MIKU = ["ミク"]
SARU = ["サル", "猿"]


def test_addressed_by_wake_word_anywhere_in_the_sentence():
    # Recognition results measured on vaio (VOICEVOX speech through ReazonSpeech).
    for text in ["ミク電気を消して", "ねえミク今日の天気は", "みくちゃんおはよう", "初音ミク歌って"]:
        assert listen.addressed(text, MIKU), text
    for text in ["猿こんにちは", "おいサル踊って", "おい猿おどって", "サルこんにちは", "さるこんにちは"]:
        assert listen.addressed(text, SARU), text


def test_not_addressed_without_a_wake_word():
    # Noise and broadcast speech seen in the chat logs.
    for text in ["あれ", "先生", "電気を消して", "最低気温十六度で晴れるでしょう", ""]:
        assert not listen.addressed(text, MIKU), text
        assert not listen.addressed(text, SARU), text
    assert not listen.addressed("ミク電気を消して", SARU)
    assert not listen.addressed("ミク電気を消して", [])


def test_strip_wake_words_keeps_the_command_as_spoken():
    for text, command in [
        ("サル、間接照明つけて", "間接照明つけて"),
        ("猿 間接照明を消して", "間接照明を消して"),
        ("間接照明つけてサル", "間接照明つけて"),
        ("さる、間接照明つけて", "間接照明つけて"),
        ("サル。間接照明を消して！", "間接照明を消して"),
        ("サル", ""),
    ]:
        assert listen.strip_wake_words(text, SARU) == command, text
