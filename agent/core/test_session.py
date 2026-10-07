import asyncio
import io
import logging
import wave

import listen
import protocol
import session
import speech
from brain import Done, TextDelta


def tiny_wav(seconds=0.01):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b"\x00\x00" * int(24000 * seconds))
    return buf.getvalue()


QUERY = {
    "speedScale": 1.0,
    "prePhonemeLength": 0.1,
    "postPhonemeLength": 0.1,
    "accent_phrases": [
        {
            "moras": [{"consonant": "k", "consonant_length": 0.05, "vowel": "a", "vowel_length": 0.1}],
            "pause_mora": None,
        }
    ],
}


class FakeBrain:
    def __init__(self, *deltas):
        self.deltas = deltas
        self.received = []

    async def reply(self, text):
        self.received.append(text)
        for delta in self.deltas:
            yield TextDelta(delta)
            await asyncio.sleep(0)
        yield Done("fake", {})


class FakeVoicevox:
    url = "fake://voicevox"

    def __init__(self, fail_from=None):
        self.calls = 0
        self.fail_from = fail_from

    async def synthesize(self, text):
        self.calls += 1
        if self.fail_from is not None and self.calls >= self.fail_from:
            raise OSError("connection refused")
        return speech.Synthesis(wav=tiny_wav(), query=QUERY)


class FakeConnection:
    def __init__(self, role):
        self.role = role
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    def of_type(self, kind):
        return [m for m in self.sent if m["type"] == kind]

    def states(self):
        return [m["state"] for m in self.of_type("state")]


class FakeStage(FakeConnection):
    """A stage that answers every speak with speak_ended, or stays silent."""

    def __init__(self, sess, reply=True):
        super().__init__("stage")
        self.sess = sess
        self.reply = reply

    async def send(self, message):
        await super().send(message)
        if self.reply and message["type"] == "speak":
            ended = {"type": "speak_ended", "id": message["id"]}
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(self.sess.handle(self, ended))
            )


async def wait_idle(sess):
    await sess.turn
    assert sess.state == "idle"


def text_input(text="こんにちは"):
    return {"type": "text_input", "text": text}


def test_two_sentences_reach_stage_and_everyone():
    async def run():
        brain = FakeBrain("こんにちは。", "元気", "だよ。")
        sess = session.Session(brain, FakeVoicevox(), ended_grace=1.0)
        stage, viewer = FakeStage(sess), FakeConnection("viewer")
        await sess.add(stage)
        await sess.add(viewer)
        await sess.handle(viewer, text_input())
        await wait_idle(sess)
        for conn in (stage, viewer):
            texts = [m["text"] for m in conn.of_type("utterance")]
            assert texts == ["こんにちは。", "元気だよ。"]
            assert all(m["who"] == "saru" for m in conn.of_type("utterance"))
            assert conn.states() == ["idle", "thinking", "speaking", "idle"]
        speaks = stage.of_type("speak")
        assert [m["text"] for m in speaks] == ["こんにちは。", "元気だよ。"]
        assert speaks[0]["id"] < speaks[1]["id"]
        assert speaks[0]["visemes"] == speech.visemes(QUERY)
        assert viewer.of_type("speak") == []

    asyncio.run(run())


def test_silent_stage_times_out_and_returns_to_idle():
    async def run():
        sess = session.Session(FakeBrain("ひとつ。"), FakeVoicevox(), ended_grace=0.05)
        stage = FakeStage(sess, reply=False)
        await sess.add(stage)
        await sess.handle(stage, text_input())
        await asyncio.wait_for(wait_idle(sess), 2)
        assert len(stage.of_type("speak")) == 1
        assert stage.states()[-1] == "idle"
        assert sess.pending == {}

    asyncio.run(run())


def test_no_stage_means_no_synthesis():
    async def run():
        voicevox = FakeVoicevox()
        sess = session.Session(FakeBrain("ひとつ。", "ふたつ。"), voicevox)
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, text_input())
        await wait_idle(sess)
        assert voicevox.calls == 0
        assert [m["text"] for m in viewer.of_type("utterance")] == ["ひとつ。", "ふたつ。"]
        assert viewer.of_type("speak") == []

    asyncio.run(run())


def test_text_input_while_busy_is_dropped():
    async def run():
        brain = FakeBrain("ひとつ。")
        sess = session.Session(brain, FakeVoicevox(), ended_grace=0.05)
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, text_input("first"))
        await sess.handle(viewer, text_input("second"))
        await wait_idle(sess)
        assert brain.received == ["first"]

    asyncio.run(run())


def test_voicevox_failure_keeps_utterances_and_stops_speaking():
    async def run():
        voicevox = FakeVoicevox(fail_from=2)
        sess = session.Session(FakeBrain("ひとつ。", "ふたつ。", "みっつ。"), voicevox)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input())
        await wait_idle(sess)
        assert [m["text"] for m in stage.of_type("utterance")] == ["ひとつ。", "ふたつ。", "みっつ。"]
        assert [m["text"] for m in stage.of_type("speak")] == ["ひとつ。"]
        # Failed once, then no more attempts for this reply.
        assert voicevox.calls == 2

    asyncio.run(run())


def test_broken_connection_is_dropped_without_stopping_the_turn():
    class Broken(FakeConnection):
        async def send(self, message):
            raise ConnectionResetError

    async def run():
        sess = session.Session(FakeBrain("ひとつ。"), FakeVoicevox())
        broken, viewer = Broken("viewer"), FakeConnection("viewer")
        sess.connections.extend([broken, viewer])
        await sess.handle(viewer, text_input())
        await wait_idle(sess)
        assert broken not in sess.connections
        assert len(viewer.of_type("utterance")) == 1

    asyncio.run(run())


def test_parse_rejects_bad_messages(caplog):
    caplog.set_level(logging.WARNING)
    assert protocol.parse("not json") is None
    assert protocol.parse("[1]") is None
    assert protocol.parse('{"type": "nope"}') is None
    assert protocol.parse('{"type": "text_input"}') is None
    assert protocol.parse('{"type": "text_input", "text": 1}') is None
    assert protocol.parse('{"type": "speak_ended", "id": "1"}') is None
    assert len(caplog.records) == 6


def test_parse_accepts_known_messages():
    assert protocol.parse('{"type": "text_input", "text": "hi"}') == {"type": "text_input", "text": "hi"}
    assert protocol.parse('{"type": "ready", "avatar": "mmd"}')["avatar"] == "mmd"
    assert protocol.parse('{"type": "speak_ended", "id": 3}')["id"] == 3
    assert protocol.parse('{"type": "motion_ended", "name": "dance"}')["name"] == "dance"


# hearing (half duplex)

SPEECH = [0.9] * listen.VAD_WINDOW
SILENCE = [0.0] * listen.VAD_WINDOW


class FakeVad:
    """A window with any sample >= 0.5 is speech; one silent window closes the segment."""

    class Segment:
        def __init__(self, samples, start):
            self.samples = samples
            self.start = start

    def __init__(self):
        self.reset()

    def reset(self):
        self.segments, self.current, self.start, self.position = [], [], 0, 0

    def accept_waveform(self, samples):
        if any(x >= 0.5 for x in samples):
            if not self.current:
                self.start = self.position
            self.current.extend(samples)
        elif self.current:
            self.flush()
        self.position += len(samples)

    def flush(self):
        if self.current:
            self.segments.append(self.Segment(self.current, self.start))
            self.current = []

    def empty(self):
        return not self.segments

    @property
    def front(self):
        return self.segments[0]

    def pop(self):
        self.segments.pop(0)


class FakeRecognizer:
    def __init__(self, text="こんにちは"):
        self.text = text
        self.calls = 0

    def __call__(self, samples):
        self.calls += 1
        return self.text


async def until(condition, timeout=2):
    while not condition():
        await asyncio.wait_for(asyncio.sleep(0.005), timeout)


def test_heard_sentence_is_answered_and_audio_until_last_speak_ended_is_dropped():
    async def run():
        brain = FakeBrain("ひとつ。", "ふたつ。")
        sess = session.Session(brain, FakeVoicevox(), ended_grace=5.0)
        stage = FakeStage(sess, reply=False)
        await sess.add(stage)
        recognizer = FakeRecognizer()
        listener = listen.Listener(FakeVad(), recognizer)

        async def blocks():
            yield SPEECH
            yield SILENCE  # the one recognition: "こんにちは"
            for n in (1, 2):
                await until(lambda: len(stage.of_type("speak")) == n)
                # saru's own voice while the speak plays: must not be recognized.
                yield SPEECH
                yield SILENCE
                speak = stage.of_type("speak")[-1]
                await sess.handle(stage, {"type": "speak_ended", "id": speak["id"]})
            await until(lambda: sess.state == "listening")

        await asyncio.wait_for(sess.listen(listener, blocks()), 5)
        assert recognizer.calls == 1
        assert brain.received == ["こんにちは"]
        assert [m["text"] for m in stage.of_type("speak")] == ["ひとつ。", "ふたつ。"]
        assert stage.of_type("utterance")[0] == {"type": "utterance", "who": "user", "text": "こんにちは"}
        assert stage.states() == ["idle", "listening", "thinking", "speaking", "listening", "idle"]
        assert listener.paused is False

    asyncio.run(run())


def test_without_stage_listening_resumes_when_the_reply_is_done():
    async def run():
        brain = FakeBrain("ひとつ。")
        sess = session.Session(brain, FakeVoicevox())
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        listener = listen.Listener(FakeVad(), FakeRecognizer())
        seen = []

        async def blocks():
            yield SPEECH
            yield SILENCE
            seen.append(listener.paused)
            await sess.wait_turn()
            seen.append((sess.state, listener.paused))
            # Heard again after resuming.
            yield SPEECH
            yield SILENCE

        await asyncio.wait_for(sess.listen(listener, blocks()), 5)
        assert seen == [True, ("listening", False)]
        assert brain.received == ["こんにちは", "こんにちは"]
        assert [m["who"] for m in viewer.of_type("utterance")] == ["user", "saru", "user", "saru"]
        assert viewer.states()[-2:] == ["listening", "idle"]

    asyncio.run(run())


def test_heard_while_busy_is_dropped():
    async def run():
        brain = FakeBrain("ひとつ。")
        sess = session.Session(brain, FakeVoicevox())
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        sess.listener = listen.Listener(FakeVad(), FakeRecognizer())
        sess.state = "listening"
        await sess.hear("first")
        await sess.hear("second")
        await sess.wait_turn()
        assert brain.received == ["first"]
        assert sess.state == "listening"

    asyncio.run(run())


def test_audio_in_waits_for_a_ready_stage():
    async def run():
        sess = session.Session(FakeBrain(), FakeVoicevox())
        viewer, stage = FakeConnection("viewer"), FakeConnection("stage")
        await sess.handle(viewer, {"type": "ready", "avatar": "mmd"})
        assert not sess.stage_ready.is_set()
        await sess.handle(stage, {"type": "ready", "avatar": "mmd"})
        assert sess.stage_ready.is_set()

    asyncio.run(run())


def test_expression_tag_rides_on_the_next_speak_and_resets_to_neutral():
    async def run():
        brain = FakeBrain("[hap", "py]やった！", "それで", "ね。[sad]でも", "残念。")
        sess = session.Session(brain, FakeVoicevox(), ended_grace=1.0)
        stage, viewer = FakeStage(sess), FakeConnection("viewer")
        await sess.add(stage)
        await sess.add(viewer)
        await sess.handle(viewer, text_input())
        await wait_idle(sess)
        speaks = stage.of_type("speak")
        assert [m["text"] for m in speaks] == ["やった！", "それでね。", "でも残念。"]
        assert [m.get("expression") for m in speaks] == ["happy", None, "sad"]
        assert [m["text"] for m in viewer.of_type("utterance")] == ["やった！", "それでね。", "でも残念。"]
        # neutral comes after the last speak was answered by speak_ended.
        assert stage.of_type("expression") == [{"type": "expression", "name": "neutral"}]
        assert stage.sent.index(stage.of_type("expression")[0]) > stage.sent.index(speaks[-1])
        assert sess.pending == {}
        assert viewer.of_type("expression") == []

    asyncio.run(run())


def test_no_stage_gets_no_expression():
    async def run():
        sess = session.Session(FakeBrain("[happy]やった。"), FakeVoicevox())
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, text_input())
        await wait_idle(sess)
        assert [m["text"] for m in viewer.of_type("utterance")] == ["やった。"]
        assert viewer.of_type("expression") == []

    asyncio.run(run())


# dance tool


class DancingBrain:
    """Calls the session's dance tool between two sentences, as Claude would."""

    def __init__(self):
        self.session = None

    async def reply(self, text):
        yield TextDelta("踊るね。")
        await self.session.dance({})
        yield TextDelta("いくよ。")
        yield Done("fake", {})


def dancing_session(**kwargs):
    brain = DancingBrain()
    brain.session = session.Session(brain, FakeVoicevox(), **kwargs)
    return brain.session


def test_dance_waits_for_the_last_speak_ended_and_holds_listening_until_motion_ended():
    async def run():
        sess = dancing_session(ended_grace=5.0, motion_timeout=5.0)
        stage = FakeStage(sess, reply=False)
        await sess.add(stage)
        sess.listener = listener = listen.Listener(FakeVad(), FakeRecognizer())
        sess.state = "listening"
        await sess.hear("踊って")
        for n in (1, 2):
            await until(lambda: len(stage.of_type("speak")) == n)
            await asyncio.sleep(0.01)
            assert stage.of_type("motion") == []
            await sess.handle(stage, {"type": "speak_ended", "id": stage.of_type("speak")[-1]["id"]})
        await until(lambda: stage.of_type("motion"))
        assert stage.of_type("motion") == [{"type": "motion", "name": "dance"}]
        await asyncio.sleep(0.01)
        assert sess.state == "speaking"
        assert listener.paused is True
        await sess.handle(stage, {"type": "motion_ended", "name": "dance"})
        await asyncio.wait_for(sess.wait_turn(), 2)
        assert sess.state == "listening"
        assert listener.paused is False
        assert stage.states()[-2:] == ["speaking", "listening"]
        assert sess.motions == {}

    asyncio.run(run())


def test_dance_times_out_without_motion_ended():
    async def run():
        sess = dancing_session(ended_grace=1.0, motion_timeout=0.05)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input("踊って"))
        await asyncio.wait_for(wait_idle(sess), 2)
        assert stage.of_type("motion") == [{"type": "motion", "name": "dance"}]

    asyncio.run(run())


def test_dance_without_stage_sends_no_motion():
    async def run():
        sess = dancing_session()
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, text_input("踊って"))
        await wait_idle(sess)
        assert viewer.of_type("motion") == []
        assert sess.dance_requested is False

    asyncio.run(run())


def test_plain_reply_sends_no_motion():
    async def run():
        sess = session.Session(FakeBrain("ひとつ。"), FakeVoicevox(), ended_grace=1.0)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input())
        await wait_idle(sess)
        assert stage.of_type("motion") == []

    asyncio.run(run())
