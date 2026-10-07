import asyncio
import io
import logging
import wave

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
