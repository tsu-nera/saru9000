import asyncio

import listen

PAD = int(listen.PAD_SECONDS * listen.SAMPLE_RATE)
WIN = listen.VAD_WINDOW
# Silence (in windows) that ends a segment in the fake VAD.
END_WINDOWS = 3


class Segment:
    def __init__(self, samples):
        self.samples = samples


class FakeVad:
    """Non-zero samples are speech; END_WINDOWS silent windows close a segment."""

    def __init__(self):
        self.received = []
        self.segments = []
        self.current = []
        self.silent = 0
        self.resets = 0

    def accept_waveform(self, samples):
        self.received.append(list(samples))
        if any(samples):
            self.current.extend(samples)
            self.silent = 0
        elif self.current:
            self.silent += 1
            if self.silent >= END_WINDOWS:
                self.close()

    def close(self):
        self.segments.append(Segment(self.current))
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
