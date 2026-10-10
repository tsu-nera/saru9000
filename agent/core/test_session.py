import asyncio
import io
import logging
import wave

import dance
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


# Not something VOICEVOX would derive: the session must pass the engine's own.
VISEMES = [{"t": 0.0, "v": "closed"}, {"t": 0.003, "v": "o"}, {"t": 0.007, "v": "closed"}]


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


class FakeEngine:
    name = "fake engine"

    def __init__(self, fail_from=None):
        self.calls = 0
        self.fail_from = fail_from

    async def synthesize(self, text):
        self.calls += 1
        if self.fail_from is not None and self.calls >= self.fail_from:
            raise OSError("connection refused")
        return speech.Synthesis(wav=tiny_wav(), visemes=VISEMES)


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
        sess = session.Session(brain, FakeEngine(), ended_grace=1.0)
        stage, viewer = FakeStage(sess), FakeConnection("viewer")
        await sess.add(stage)
        await sess.add(viewer)
        await sess.handle(viewer, text_input())
        await wait_idle(sess)
        for conn in (stage, viewer):
            texts = [m["text"] for m in conn.of_type("utterance")]
            assert texts == ["こんにちは。", "元気だよ。"]
            assert all(m["who"] == "agent" for m in conn.of_type("utterance"))
            assert conn.states() == ["idle", "thinking", "speaking", "idle"]
        speaks = stage.of_type("speak")
        assert [m["text"] for m in speaks] == ["こんにちは。", "元気だよ。"]
        assert speaks[0]["id"] < speaks[1]["id"]
        assert speaks[0]["visemes"] == VISEMES
        assert viewer.of_type("speak") == []

    asyncio.run(run())


def test_silent_stage_times_out_and_returns_to_idle():
    async def run():
        sess = session.Session(FakeBrain("ひとつ。"), FakeEngine(), ended_grace=0.05)
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
        engine = FakeEngine()
        sess = session.Session(FakeBrain("ひとつ。", "ふたつ。"), engine)
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, text_input())
        await wait_idle(sess)
        assert engine.calls == 0
        assert [m["text"] for m in viewer.of_type("utterance")] == ["ひとつ。", "ふたつ。"]
        assert viewer.of_type("speak") == []

    asyncio.run(run())


def test_text_input_while_busy_is_dropped():
    async def run():
        brain = FakeBrain("ひとつ。")
        sess = session.Session(brain, FakeEngine(), ended_grace=0.05)
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, text_input("first"))
        await sess.handle(viewer, text_input("second"))
        await wait_idle(sess)
        assert brain.received == ["first"]

    asyncio.run(run())


def test_engine_failure_keeps_utterances_and_stops_speaking():
    async def run():
        engine = FakeEngine(fail_from=2)
        sess = session.Session(FakeBrain("ひとつ。", "ふたつ。", "みっつ。"), engine)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input())
        await wait_idle(sess)
        assert [m["text"] for m in stage.of_type("utterance")] == ["ひとつ。", "ふたつ。", "みっつ。"]
        assert [m["text"] for m in stage.of_type("speak")] == ["ひとつ。"]
        # Failed once, then no more attempts for this reply.
        assert engine.calls == 2

    asyncio.run(run())


def test_broken_connection_is_dropped_without_stopping_the_turn():
    class Broken(FakeConnection):
        async def send(self, message):
            raise ConnectionResetError

    async def run():
        sess = session.Session(FakeBrain("ひとつ。"), FakeEngine())
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
    assert protocol.parse('{"type": "listen_mode", "mode": "wake"}')["mode"] == "wake"
    assert protocol.parse('{"type": "listen_mode"}') is None
    assert protocol.parse('{"type": "stop_motion"}') == {"type": "stop_motion"}


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
        sess = session.Session(brain, FakeEngine(), ended_grace=5.0)
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
        sess = session.Session(brain, FakeEngine())
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
        assert [m["who"] for m in viewer.of_type("utterance")] == ["user", "agent", "user", "agent"]
        assert viewer.states()[-2:] == ["listening", "idle"]

    asyncio.run(run())


def test_heard_while_busy_is_dropped():
    async def run():
        brain = FakeBrain("ひとつ。")
        sess = session.Session(brain, FakeEngine())
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
        sess = session.Session(FakeBrain(), FakeEngine())
        viewer, stage = FakeConnection("viewer"), FakeConnection("stage")
        await sess.handle(viewer, {"type": "ready", "avatar": "mmd"})
        assert not sess.stage_ready.is_set()
        await sess.handle(stage, {"type": "ready", "avatar": "mmd"})
        assert sess.stage_ready.is_set()

    asyncio.run(run())


def test_expression_tag_rides_on_the_next_speak_and_resets_to_neutral():
    async def run():
        brain = FakeBrain("[hap", "py]やった！", "それで", "ね。[sad]でも", "残念。")
        sess = session.Session(brain, FakeEngine(), ended_grace=1.0)
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
        sess = session.Session(FakeBrain("[happy]やった。"), FakeEngine())
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, text_input())
        await wait_idle(sess)
        assert [m["text"] for m in viewer.of_type("utterance")] == ["やった。"]
        assert viewer.of_type("expression") == []

    asyncio.run(run())


# dance


CUE = "ミュージック、スタート！"
DANCES = dance.Dances.from_config(
    {
        "cue": CUE,
        "menu": {"phrases": ["踊って", "踊れる"], "cancel": "また今度ね。"},
        "songs": [
            {"motion": "mikumiku", "name": "ミクミク", "phrases": ["ミクミクにして"], "choices": ["ミクミク", "1番"]},
            {"motion": "tellyourworld", "name": "テルユア", "phrases": ["テルユアワールド"], "choices": ["2番"]},
        ],
    }
)
MIKUMIKU = {"type": "motion", "name": "mikumiku"}


def dancing_session(**kwargs):
    brain = FakeBrain("ここは呼ばれない。")
    return session.Session(brain, FakeEngine(), dances=DANCES, **kwargs), brain


def test_dance_phrase_skips_the_brain_says_the_cue_then_holds_listening_until_motion_ended():
    async def run():
        sess, brain = dancing_session(ended_grace=5.0, motion_timeout=5.0)
        stage = FakeStage(sess, reply=False)
        await sess.add(stage)
        sess.listener = listener = listen.Listener(FakeVad(), FakeRecognizer())
        sess.state = "listening"
        await sess.hear("ミクミクにして")
        await until(lambda: stage.of_type("speak"))
        await asyncio.sleep(0.01)
        assert [m["text"] for m in stage.of_type("speak")] == [CUE]
        assert stage.of_type("motion") == []
        await sess.handle(stage, {"type": "speak_ended", "id": stage.of_type("speak")[-1]["id"]})
        await until(lambda: stage.of_type("motion"))
        assert stage.of_type("motion") == [MIKUMIKU]
        await asyncio.sleep(0.01)
        assert sess.state == "speaking"
        assert listener.paused is True
        await sess.handle(stage, {"type": "motion_ended", "name": "mikumiku"})
        await asyncio.wait_for(sess.wait_turn(), 2)
        assert sess.state == "listening"
        assert listener.paused is False
        assert stage.states()[-2:] == ["speaking", "listening"]
        assert sess.motions == {}
        assert brain.received == []

    asyncio.run(run())


def test_each_song_phrase_sends_its_own_motion():
    async def run():
        sess, brain = dancing_session(ended_grace=1.0, motion_timeout=0.05)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input("テルユアワールド"))
        await asyncio.wait_for(wait_idle(sess), 2)
        assert stage.of_type("motion") == [{"type": "motion", "name": "tellyourworld"}]
        assert brain.received == []

    asyncio.run(run())


def test_menu_lists_the_songs_and_the_next_sentence_picks_one_without_a_wake_word():
    async def run():
        sess, brain = dancing_session(ended_grace=1.0, motion_timeout=0.05, listen_mode="wake", wake_words=("ミク",))
        stage = FakeStage(sess)
        await sess.add(stage)
        sess.listener = listen.Listener(FakeVad(), FakeRecognizer())
        sess.state = "listening"
        await sess.hear("ミク、何が踊れる？")
        await sess.wait_turn()
        assert [m["text"] for m in stage.of_type("speak")] == ["ミクミクと、テルユアが踊れるよ。どれにする？"]
        await sess.hear("2番")
        await sess.wait_turn()
        assert [m["text"] for m in stage.of_type("speak")][-1] == CUE
        assert stage.of_type("motion") == [{"type": "motion", "name": "tellyourworld"}]
        assert brain.received == []

    asyncio.run(run())


def test_menu_answer_that_picks_nothing_gets_the_cancel_line_and_closes_the_menu():
    async def run():
        sess, brain = dancing_session()
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        for text in ["踊って", "やっぱりいいや", "2番"]:
            await sess.handle(viewer, text_input(text))
            await sess.wait_turn()
        said = [m["text"] for m in viewer.of_type("utterance") if m["who"] == "agent"]
        assert said[1] == "また今度ね。"
        # The menu is closed: 「2番」 goes to the brain.
        assert brain.received == ["2番"]

    asyncio.run(run())


def test_menu_closes_after_its_time():
    async def run():
        sess, brain = dancing_session(follow_up_window=0.0)
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        for text in ["踊って", "ミクミク"]:
            await sess.handle(viewer, text_input(text))
            await sess.wait_turn()
        assert brain.received == ["ミクミク"]
        assert viewer.of_type("motion") == []

    asyncio.run(run())


def test_stop_motion_reaches_the_stage_and_its_motion_ended_finishes_the_turn():
    async def run():
        sess, _ = dancing_session(ended_grace=1.0, motion_timeout=5.0)
        stage = FakeStage(sess)
        viewer = FakeConnection("viewer")
        await sess.add(stage)
        await sess.add(viewer)
        await sess.handle(viewer, text_input("ミクミクにして"))
        await until(lambda: stage.of_type("motion"))
        await sess.handle(viewer, {"type": "stop_motion"})
        assert stage.of_type("stop_motion") == [{"type": "stop_motion"}]
        await sess.handle(stage, {"type": "motion_ended", "name": "mikumiku"})
        await asyncio.wait_for(wait_idle(sess), 2)

    asyncio.run(run())


def test_stop_motion_frees_the_turn_when_the_stage_never_answers():
    async def run():
        sess, _ = dancing_session(ended_grace=1.0, motion_timeout=5.0, stop_timeout=0.05)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input("ミクミクにして"))
        await until(lambda: stage.of_type("motion"))
        await sess.handle(stage, {"type": "stop_motion"})
        await asyncio.wait_for(wait_idle(sess), 1)

    asyncio.run(run())


def test_stop_motion_without_a_dance_does_nothing():
    async def run():
        sess, _ = dancing_session()
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, {"type": "stop_motion"})
        assert stage.of_type("stop_motion") == []

    asyncio.run(run())


def test_dance_times_out_without_motion_ended():
    async def run():
        sess, _ = dancing_session(ended_grace=1.0, motion_timeout=0.05)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input("ミクミクにして"))
        await asyncio.wait_for(wait_idle(sess), 2)
        assert stage.of_type("motion") == [MIKUMIKU]

    asyncio.run(run())


def test_dance_without_stage_says_the_cue_as_text_and_sends_no_motion():
    async def run():
        sess, brain = dancing_session()
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, text_input("ミクミクにして"))
        await wait_idle(sess)
        assert viewer.of_type("motion") == []
        assert [m["text"] for m in viewer.of_type("utterance")] == [CUE]
        assert brain.received == []

    asyncio.run(run())


class FakeHome:
    """Records each lights call into log (a stage's sent list, to see the order), or raises."""

    def __init__(self, log, fail=False):
        self.log = log
        self.fail = fail

    async def _call(self, name):
        self.log.append({"type": "lights", "name": name})
        if self.fail:
            raise RuntimeError("home assistant is down")

    async def dance_lights_blackout(self):
        await self._call("blackout")

    async def dance_lights_start(self):
        await self._call("start")

    async def dance_lights_end(self):
        await self._call("end")


def lights_and_stage(conn):
    return [
        m["name"] if m["type"] == "lights" else m["type"]
        for m in conn.sent
        if m["type"] in ("lights", "speak", "motion")
    ]


def test_dance_lights_go_out_before_the_cue_start_before_the_motion_and_end_after():
    async def run():
        sess, _ = dancing_session(ended_grace=1.0, motion_timeout=5.0)
        stage = FakeStage(sess)
        sess.home = FakeHome(stage.sent)
        await sess.add(stage)
        await sess.handle(stage, text_input("ミクミクにして"))
        await until(lambda: stage.of_type("motion"))
        assert lights_and_stage(stage) == ["blackout", "speak", "start", "motion"]
        await sess.handle(stage, {"type": "motion_ended", "name": "mikumiku"})
        await asyncio.wait_for(wait_idle(sess), 2)
        assert lights_and_stage(stage) == ["blackout", "speak", "start", "motion", "end"]

    asyncio.run(run())


def test_dance_lights_end_when_motion_ended_never_comes():
    async def run():
        sess, _ = dancing_session(ended_grace=1.0, motion_timeout=0.05)
        stage = FakeStage(sess)
        sess.home = FakeHome(stage.sent)
        await sess.add(stage)
        await sess.handle(stage, text_input("ミクミクにして"))
        await asyncio.wait_for(wait_idle(sess), 2)
        assert lights_and_stage(stage) == ["blackout", "speak", "start", "motion", "end"]

    asyncio.run(run())


def test_failing_lights_do_not_stop_the_dance():
    async def run():
        sess, _ = dancing_session(ended_grace=1.0, motion_timeout=0.05)
        stage = FakeStage(sess)
        sess.home = FakeHome(stage.sent, fail=True)
        await sess.add(stage)
        await sess.handle(stage, text_input("ミクミクにして"))
        await asyncio.wait_for(wait_idle(sess), 2)
        assert lights_and_stage(stage) == ["blackout", "speak", "start", "motion", "end"]
        assert stage.states()[-1] == "idle"

    asyncio.run(run())


def test_dance_without_stage_touches_no_lights():
    async def run():
        sess, _ = dancing_session()
        calls = []
        sess.home = FakeHome(calls)
        await sess.add(FakeConnection("viewer"))
        await sess.handle(sess.connections[0], text_input("ミクミクにして"))
        await wait_idle(sess)
        assert calls == []

    asyncio.run(run())


def test_plain_reply_touches_no_lights():
    async def run():
        sess = session.Session(FakeBrain("ひとつ。"), FakeEngine(), ended_grace=1.0)
        stage = FakeStage(sess)
        calls = []
        sess.home = FakeHome(calls)
        await sess.add(stage)
        await sess.handle(stage, text_input())
        await wait_idle(sess)
        assert calls == []
        assert len(stage.of_type("speak")) == 1

    asyncio.run(run())


def test_plain_reply_sends_no_motion():
    async def run():
        sess = session.Session(FakeBrain("ひとつ。"), FakeEngine(), ended_grace=1.0)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input())
        await wait_idle(sess)
        assert stage.of_type("motion") == []

    asyncio.run(run())


# listen mode

def heard_session(listen_mode, wake_words=("ミク",), **kwargs):
    brain = FakeBrain("はい。")
    sess = session.Session(brain, FakeEngine(), listen_mode=listen_mode, wake_words=wake_words, **kwargs)
    sess.listener = listen.Listener(FakeVad(), FakeRecognizer())
    sess.state = "listening"
    return sess, brain


def test_wake_mode_drops_heard_without_a_wake_word(caplog):
    caplog.set_level(logging.INFO)

    async def run():
        sess, brain = heard_session("wake")
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.hear("電気を消して")
        assert sess.turn is None
        assert sess.state == "listening"
        assert sess.listener.paused is False
        assert brain.received == []
        assert viewer.of_type("utterance") == []
        assert viewer.states() == ["listening"]

    asyncio.run(run())
    assert "dropped heard '電気を消して': no wake word" in caplog.text


def test_wake_mode_answers_heard_with_a_wake_word():
    async def run():
        sess, brain = heard_session("wake")
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        for text in ["ミク電気を消して", "ねえみく今日の天気は"]:
            await sess.hear(text)
            await sess.wait_turn()
        # The wake word stays in the text Claude gets.
        assert brain.received == ["ミク電気を消して", "ねえみく今日の天気は"]
        assert [m["text"] for m in viewer.of_type("utterance") if m["who"] == "user"] == brain.received

    asyncio.run(run())


def agent_says(conn):
    return [m["text"] for m in conn.of_type("utterance") if m["who"] == "agent"]


def test_bare_wake_word_gets_the_wake_reply_then_the_next_sentence_needs_none():
    async def run():
        sess, brain = heard_session("wake", wake_reply="うん")
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.hear("ミク。")
        await sess.wait_turn()
        assert brain.received == []
        assert agent_says(viewer) == ["うん"]
        await sess.hear("電気を消して")
        await sess.wait_turn()
        assert brain.received == ["電気を消して"]
        # The window is used up: the one after needs the wake word again.
        await sess.hear("テレビをつけて")
        assert sess.turn.done()
        assert brain.received == ["電気を消して"]

    asyncio.run(run())


def test_wake_window_closes_after_its_time():
    async def run():
        sess, brain = heard_session("wake", wake_reply="はい", follow_up_window=0.0)
        await sess.hear("ミク")
        await sess.wait_turn()
        await sess.hear("電気を消して")
        assert brain.received == []

    asyncio.run(run())


def test_wake_word_with_a_request_goes_straight_to_the_brain():
    async def run():
        sess, brain = heard_session("wake", wake_reply="はい")
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.hear("ミク、電気を消して")
        await sess.wait_turn()
        assert brain.received == ["ミク、電気を消して"]
        assert agent_says(viewer) == ["はい。"]  # FakeBrain's answer, no wake reply before it

    asyncio.run(run())


def test_without_wake_reply_a_bare_wake_word_goes_to_the_brain():
    async def run():
        sess, brain = heard_session("wake")
        await sess.hear("ミク")
        await sess.wait_turn()
        assert brain.received == ["ミク"]

    asyncio.run(run())


def test_always_mode_answers_every_heard_sentence():
    async def run():
        sess, brain = heard_session("always")
        await sess.hear("電気を消して")
        await sess.wait_turn()
        assert brain.received == ["電気を消して"]

    asyncio.run(run())


def test_text_input_is_answered_in_both_modes():
    async def run():
        for mode in protocol.LISTEN_MODES:
            sess, brain = heard_session(mode)
            await sess.handle(FakeConnection("viewer"), text_input("電気を消して"))
            await sess.wait_turn()
            assert brain.received == ["電気を消して"], mode

    asyncio.run(run())


def test_new_connection_gets_the_state_then_the_listen_mode():
    async def run():
        sess = session.Session(FakeBrain(), FakeEngine(), listen_mode="wake")
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        assert viewer.sent == [protocol.state("idle"), protocol.listen_mode("wake")]

    asyncio.run(run())


def test_listen_mode_message_switches_and_reaches_everyone():
    async def run():
        sess, brain = heard_session("wake")
        stage, viewer = FakeStage(sess), FakeConnection("viewer")
        await sess.add(stage)
        await sess.add(viewer)
        await sess.handle(viewer, {"type": "listen_mode", "mode": "always"})
        assert sess.listen_mode == "always"
        for conn in (stage, viewer):
            assert conn.of_type("listen_mode")[-1] == protocol.listen_mode("always")
        await sess.hear("電気を消して")
        await sess.wait_turn()
        assert brain.received == ["電気を消して"]
        await sess.handle(viewer, {"type": "listen_mode", "mode": "wake"})
        assert sess.listen_mode == "wake"
        assert viewer.of_type("listen_mode")[-1] == protocol.listen_mode("wake")

    asyncio.run(run())


def test_unknown_listen_mode_is_dropped(caplog):
    caplog.set_level(logging.WARNING)

    async def run():
        sess, _ = heard_session("wake")
        viewer = FakeConnection("viewer")
        await sess.add(viewer)
        await sess.handle(viewer, {"type": "listen_mode", "mode": "sometimes"})
        assert sess.listen_mode == "wake"
        assert len(viewer.of_type("listen_mode")) == 1  # only the one on connect

    asyncio.run(run())
    assert "unknown mode 'sometimes'" in caplog.text


def test_switching_the_mode_does_not_touch_a_turn_in_progress():
    async def run():
        sess, brain = heard_session("always")
        stage = FakeStage(sess, reply=False)
        await sess.add(stage)
        sess.ended_grace = 5.0
        await sess.hear("こんにちは")
        await until(lambda: len(stage.of_type("speak")) == 1)
        await sess.handle(stage, {"type": "listen_mode", "mode": "wake"})
        assert sess.state == "speaking"
        await sess.handle(stage, {"type": "speak_ended", "id": stage.of_type("speak")[0]["id"]})
        await sess.wait_turn()
        assert brain.received == ["こんにちは"]

    asyncio.run(run())


# log lines for the stage's screen


def logs_of(conn, kind=None):
    return [m for m in conn.of_type("log") if kind is None or m["kind"] == kind]


def stage_logger(sess, name="test_stage_log"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    handler = session.StageLogHandler(sess, asyncio.get_running_loop())
    logger.addHandler(handler)
    return logger, handler


async def flush_logs(sess):
    await asyncio.sleep(0)
    await sess.logs.join()


def test_info_and_up_reach_the_stage_only_as_system_lines():
    async def run():
        sess = session.Session(FakeBrain(), FakeEngine())
        stage, viewer = FakeStage(sess), FakeConnection("viewer")
        await sess.add(stage)
        await sess.add(viewer)
        logger, handler = stage_logger(sess)
        access, access_handler = stage_logger(sess, "aiohttp.access")
        try:
            logger.debug("hidden")
            logger.info("shown %d", 1)
            logger.warning("careful")
            access.info("GET / 200")
            await flush_logs(sess)
        finally:
            logger.removeHandler(handler)
            access.removeHandler(access_handler)
        assert [(m["kind"], m["text"], m["append"]) for m in logs_of(stage)] == [
            ("system", "test_stage_log: shown 1", False),
            ("system", "test_stage_log: careful", False),
        ]
        assert logs_of(viewer) == []

    asyncio.run(run())


def test_log_kind_extra_sets_the_kind_without_the_logger_name():
    async def run():
        sess = session.Session(FakeBrain(), FakeEngine())
        stage = FakeStage(sess)
        await sess.add(stage)
        logger, handler = stage_logger(sess)
        try:
            logger.info("%s %s", "weather", "{}", extra=protocol.log_kind("tool"))
            await flush_logs(sess)
        finally:
            logger.removeHandler(handler)
        assert [(m["kind"], m["text"]) for m in logs_of(stage)] == [("tool", "weather {}")]

    asyncio.run(run())


def test_log_from_another_thread_arrives():
    async def run():
        sess = session.Session(FakeBrain(), FakeEngine())
        stage = FakeStage(sess)
        await sess.add(stage)
        logger, handler = stage_logger(sess)
        try:
            await asyncio.to_thread(logger.info, "from a thread")
            await flush_logs(sess)
        finally:
            logger.removeHandler(handler)
        assert [m["text"] for m in logs_of(stage)] == ["test_stage_log: from a thread"]

    asyncio.run(run())


def test_failing_stage_send_does_not_loop_through_the_log_handler():
    attempts = []

    class BrokenStage(FakeConnection):
        async def send(self, message):
            if message["type"] != "log":
                return
            attempts.append(message)
            raise ConnectionError("gone")

    async def run():
        sess = session.Session(FakeBrain(), FakeEngine())
        stage = BrokenStage("stage")
        await sess.add(stage)
        # The pump's own "send failed" record goes to this very handler.
        sender, sender_handler = stage_logger(sess, "session")
        logger, handler = stage_logger(sess)
        try:
            logger.info("one")
            await flush_logs(sess)
            await flush_logs(sess)
            logger.info("two")
            await flush_logs(sess)
        finally:
            logger.removeHandler(handler)
            sender.removeHandler(sender_handler)
        assert sess.connections == []
        assert len(attempts) == 1
        assert sess.logs.empty()

    asyncio.run(run())


def test_claude_fragments_are_logged_raw_in_order_after_the_user_line():
    async def run():
        sess = session.Session(FakeBrain("こん", "[happy]にちは。"), FakeEngine(), ended_grace=1.0)
        stage, viewer = FakeStage(sess), FakeConnection("viewer")
        await sess.add(stage)
        await sess.add(viewer)
        await sess.handle(viewer, text_input("やあ"))
        await wait_idle(sess)
        await flush_logs(sess)
        lines = logs_of(stage)
        assert lines[0]["kind"] == "user" and lines[0]["text"] == "やあ"
        assert [(m["kind"], m["text"], m["append"]) for m in lines if m["kind"] == "claude"] == [
            ("claude", "こん", True),
            ("claude", "[happy]にちは。", True),
        ]
        assert logs_of(viewer) == []

    asyncio.run(run())


def test_heard_sentence_is_logged_as_user():
    async def run():
        sess, brain = heard_session("always")
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.hear("こんにちは")
        await sess.wait_turn()
        await flush_logs(sess)
        assert [m["text"] for m in logs_of(stage, "user")] == ["こんにちは"]

    asyncio.run(run())


def test_fixed_answers_are_not_logged_as_claude():
    async def run():
        sess, brain = heard_session("wake", wake_reply="はい")
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.hear("ミク")
        await sess.wait_turn()
        await flush_logs(sess)
        assert logs_of(stage, "claude") == []
        assert [m["text"] for m in logs_of(stage, "user")] == ["ミク"]

    asyncio.run(run())


def test_each_spoken_chunk_logs_its_vowel_timeline():
    async def run():
        sess = session.Session(FakeBrain("ひとつ。", "ふたつ。"), FakeEngine(), ended_grace=1.0)
        stage = FakeStage(sess)
        await sess.add(stage)
        await sess.handle(stage, text_input())
        await wait_idle(sess)
        await flush_logs(sess)
        speech_lines = logs_of(stage, "speech")
        assert len(speech_lines) == len(stage.of_type("speak")) == 2
        assert all(m["text"] == session.vowel_timeline(VISEMES) == "o0.00" for m in speech_lines)

    asyncio.run(run())


def test_vowel_timeline_drops_closed_and_keeps_order():
    visemes = [{"t": 0.0, "v": "closed"}, {"t": 0.12, "v": "a"}, {"t": 0.3, "v": "i"}, {"t": 0.4, "v": "closed"}]
    assert session.vowel_timeline(visemes) == "a0.12 i0.30"
    assert session.vowel_timeline([]) == ""
