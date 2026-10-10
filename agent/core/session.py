"""One saru session: connections, state, and the turn from text_input to idle.

With a listener (listen.py) the session is half duplex: hearing a sentence
pauses the listener, and it resumes once the turn is over, i.e. after the
last speak_ended (or its timeout), or after the text-only reply.

A turn runs as three stages: the brain's text is cut
into chunks, a producer synthesizes them ahead, and a consumer delivers them to
the stage one at a time. Expression tags in the text ("[happy]") are taken
out before chunking and ride on the speak of the chunk after them; the face
goes back to neutral after the last speak_ended.

Dances (dance.py) skip the brain: a song's phrase makes the core say its cue,
the stage dances after it, and the turn (still speaking, listener still paused)
lasts until motion_ended. With a stage and an injected home, the room's lights
go out before the cue, change color through the dance, and come back after it.
A menu phrase lists the songs, and the next sentence picks one.

In wake mode a heard sentence without a wake word is dropped before a turn
starts, and one that is only a wake word gets the character's wake_reply
("はい") instead of the brain. After the wake reply or the dance menu, the next
sentence heard within FOLLOW_UP_WINDOW seconds needs no wake word. text_input
is answered in either mode. Only stdlib and sibling modules are imported so
the tests need no aiohttp or Claude SDK.
"""

import asyncio
import itertools
import logging

import dance as dances_
import expression
import listen
import protocol
import speech
from brain import Done, TextDelta

log = logging.getLogger(__name__)

# speak ids are unique per process, shared by every session.
_speak_ids = itertools.count(1)

# A dance is about 100 s; a stage that never answers frees the turn after this.
MOTION_TIMEOUT = 180.0
# After a stop_motion, how long the stage gets to answer with motion_ended.
STOP_TIMEOUT = 3.0

# After the wake_reply or the dance menu, how long the next heard sentence needs
# no wake word. Only after those and for one sentence: opened after every
# answer, noise heard right after it chained answers.
FOLLOW_UP_WINDOW = 10.0


class Session:
    def __init__(
        self,
        brain,
        engine,
        name="agent",
        ended_grace=2.0,
        motion_timeout=MOTION_TIMEOUT,
        stop_timeout=STOP_TIMEOUT,
        listen_mode="always",
        wake_words=(),
        wake_reply=None,
        follow_up_window=FOLLOW_UP_WINDOW,
        home=None,
        dances=None,
    ):
        self.brain = brain
        # The dance's lights: the home module, or None for no lights.
        self.home = home
        self.name = name  # the character, shown next to its utterances
        self.engine = engine  # speech.Voicevox or speech.OpenJTalk
        # How long past the wav length a missing speak_ended is waited for.
        self.ended_grace = ended_grace
        self.motion_timeout = motion_timeout
        self.stop_timeout = stop_timeout
        self.state = "idle"
        # "wake": heard sentences without a wake word are dropped; "always": all are answered.
        self.listen_mode = listen_mode
        self.wake_words = wake_words
        self.wake_reply = wake_reply  # said to a bare wake word; None: no reply, the brain answers
        self.follow_up_window = follow_up_window
        # (kind, loop time until): the next sentence answers "wake" or the "dance" menu.
        self.follow_up = None
        self.dances = dances if dances is not None else dances_.Dances()
        self.connections = []
        self.turn = None
        self.pending = {}  # speak id -> Future resolved by speak_ended
        self.motions = {}  # motion name -> Future resolved by motion_ended
        self.listener = None  # listen.Listener while hearing the user
        # Set by the first ready from a stage; --audio-in waits for it.
        self.stage_ready = asyncio.Event()

    # connections

    async def add(self, conn):
        self.connections.append(conn)
        await self._send(conn, protocol.state(self.state))
        await self._send(conn, protocol.listen_mode(self.listen_mode))

    def remove(self, conn):
        if conn in self.connections:
            self.connections.remove(conn)

    def _stage(self):
        # The most recently added stage wins.
        for conn in reversed(self.connections):
            if conn.role == "stage":
                return conn
        return None

    async def _send(self, conn, message):
        try:
            await conn.send(message)
        except Exception:
            log.exception("send to %s failed, dropping the connection", conn.role)
            self.remove(conn)

    async def _broadcast(self, message):
        for conn in list(self.connections):
            await self._send(conn, message)

    async def _set_state(self, name):
        self.state = name
        await self._broadcast(protocol.state(name))

    def _resting(self):
        return "listening" if self.listener is not None else "idle"

    # hearing

    async def listen(self, listener, blocks, one_at_a_time=False):
        """Hear the user from blocks until they run out, then stop listening.

        one_at_a_time waits for each turn before reading on: wav files are
        read faster than real time, and their audio would otherwise be
        dropped by the paused listener. The microphone must keep being read.
        """
        self.listener = listener
        if self.state == "idle":
            await self._set_state("listening")
        try:
            async for text in listen.utterances(listener, blocks):
                await self.hear(text)
                if one_at_a_time:
                    await self.wait_turn()
            await self.wait_turn()
        finally:
            self.listener = None
            if self.state == "listening":
                await self._set_state("idle")

    async def hear(self, text):
        """A sentence the listener recognized: answer it like a text_input."""
        if self.state != "listening":
            log.info("dropped heard %r while %s", text, self.state)
            return
        if self.listen_mode == "wake":
            addressed = listen.addressed(text, self.wake_words)
            if addressed and self.wake_reply and not listen.strip_wake_words(text, self.wake_words):
                self._start_turn(text, heard=True, reply=self.wake_reply)
                return
            if not addressed:
                follow = self._follow_up()
                if follow is None:
                    log.info("dropped heard %r: no wake word", text)
                    return
                log.info("heard %r right after the %s answer", text, follow)
        self._start_turn(text, heard=True)

    def _follow_up(self):
        """The open follow-up's kind, or None."""
        if self.follow_up is None:
            return None
        kind, until = self.follow_up
        return kind if asyncio.get_running_loop().time() < until else None

    async def wait_turn(self):
        if self.turn is not None:
            await asyncio.gather(self.turn, return_exceptions=True)

    def _start_turn(self, text, heard=False, reply=None):
        # Set before the first await so a second input cannot slip in.
        self.state = "thinking"
        follow = self._follow_up()
        self.follow_up = None
        if self.listener is not None:
            self.listener.pause()
        self.turn = asyncio.create_task(self._run_turn(text, heard, reply, follow))

    # incoming

    async def handle(self, conn, message):
        kind = message["type"]
        if kind == "text_input":
            if self.state not in ("idle", "listening"):
                log.info("dropped text_input while %s", self.state)
                return
            self._start_turn(message["text"])
        elif kind == "listen_mode":
            mode = message["mode"]
            if mode not in protocol.LISTEN_MODES:
                log.warning("dropped listen_mode: unknown mode %r", mode)
                return
            # Only the setting changes; a turn in progress is not touched.
            self.listen_mode = mode
            await self._broadcast(protocol.listen_mode(mode))
        elif kind == "ready":
            if conn.role == "stage":
                self.stage_ready.set()
        elif kind == "speak_ended":
            future = self.pending.get(message["id"])
            if future is not None and not future.done():
                future.set_result(None)
        elif kind == "motion_ended":
            future = self.motions.get(message["name"])
            if future is not None and not future.done():
                future.set_result(None)
        elif kind == "stop_motion":
            await self._stop_motion()
        else:
            log.debug("ignored %s", kind)

    async def _stop_motion(self):
        """Ask the stage to stop the one-shot motion; past stop_timeout, stop waiting for it."""
        if not self.motions:
            log.info("stop_motion: nothing is playing")
            return
        log.info("stop_motion: %s", ", ".join(self.motions))
        stage = self._stage()
        if stage is not None:
            await self._send(stage, protocol.stop_motion())
        loop = asyncio.get_running_loop()
        for future in self.motions.values():
            loop.call_later(self.stop_timeout, lambda f=future: f.done() or f.set_result(None))

    async def close(self):
        if self.turn is not None:
            self.turn.cancel()
            await asyncio.gather(self.turn, return_exceptions=True)

    # turn

    def _fixed_answer(self, text, reply, follow):
        """(words, dance, follow-up to open) said instead of asking the brain, or None.

        reply is the wake reply; follow the follow-up this sentence answers.
        """
        if reply is not None:
            return reply, None, "wake"
        if follow == "dance":
            song = self.dances.chosen(text)
            if song is None:
                return self.dances.cancel, None, None
            return song.cue, song, None
        song = self.dances.requested(text)
        if song is not None:
            return song.cue, song, None
        if self.dances.asks_menu(text):
            return self.dances.menu(), None, "dance"
        return None

    async def _run_turn(self, text, heard=False, reply=None, follow=None):
        stage_at_start = self._stage() is not None
        texts, sounds = asyncio.Queue(), asyncio.Queue()
        workers = [
            asyncio.create_task(self._synthesize_all(texts, sounds, stage_at_start)),
            asyncio.create_task(self._deliver_all(sounds)),
        ]
        extractor = expression.Extractor()
        chunker = speech.Chunker()
        face = None  # the last tag, until a chunk starts after it
        lit = False  # the dance's lights were set off this turn

        def put(parts):
            nonlocal face
            for part in parts:
                if isinstance(part, expression.Tag):
                    face = part.name
                    continue
                for chunk in chunker.feed(part):
                    texts.put_nowait((chunk, face))
                    face = None

        try:
            if heard:
                await self._broadcast(protocol.utterance("user", text))
            await self._broadcast(protocol.state("thinking"))
            fixed = self._fixed_answer(text, reply, follow)
            song = then = None
            if fixed is not None:
                words, song, then = fixed
                if song is not None:
                    log.info("dance %s requested", song.motion)
                    # Without a stage there is no dance, so no lights either.
                    if self.home is not None and stage_at_start:
                        lit = True
                        await self._lights("dance_lights_blackout")
                texts.put_nowait((words, "happy" if song is not None else None))
            else:
                async for event in self.brain.reply(text):
                    if isinstance(event, TextDelta):
                        put(extractor.feed(event.text))
                    elif isinstance(event, Done):
                        break
                put(extractor.flush())
                for chunk in chunker.flush():
                    texts.put_nowait((chunk, face))
            texts.put_nowait(None)
            await asyncio.gather(*workers)
            if song is not None:
                if lit:
                    await self._lights("dance_lights_start")
                await self._play_motion(song.motion)
            if then is not None:
                self.follow_up = (then, asyncio.get_running_loop().time() + self.follow_up_window)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("turn failed")
        finally:
            for worker in workers:
                worker.cancel()
            if lit:
                await self._lights("dance_lights_end")
            if self.listener is not None:
                self.listener.resume()
            await self._set_state(self._resting())

    async def _lights(self, name):
        # The lights are a show on the side: their failure must not stop the turn.
        try:
            await getattr(self.home, name)()
        except Exception:
            log.exception("%s failed", name)

    async def _synthesize_all(self, texts, sounds, enabled):
        while (item := await texts.get()) is not None:
            text, face = item
            synthesis = None
            if enabled:
                try:
                    synthesis = await self.engine.synthesize(text)
                except (OSError, ValueError) as e:
                    log.warning("%s failed, text only for the rest: %s", self.engine.name, e)
                    enabled = False
            sounds.put_nowait((text, face, synthesis))
        sounds.put_nowait(None)

    async def _deliver_all(self, sounds):
        first = True
        faced = False  # the stage was told a face or a speak this turn
        while (item := await sounds.get()) is not None:
            text, face, synthesis = item
            if first:
                first = False
                await self._set_state("speaking")
            stage = self._stage() if synthesis else None
            if stage is None:
                if face is not None and (fallback := self._stage()) is not None:
                    # Unspoken text still changes the face.
                    await self._send(fallback, protocol.expression(face))
                    faced = True
                await self._broadcast(protocol.utterance("agent", text, self.name))
                continue
            faced = True
            id = next(_speak_ids)
            future = asyncio.get_running_loop().create_future()
            self.pending[id] = future
            try:
                await self._send(
                    stage,
                    protocol.speak(id, text, synthesis.wav, synthesis.visemes, face),
                )
                await self._broadcast(protocol.utterance("agent", text, self.name))
                if stage not in self.connections:
                    # The send failed and the stage was dropped: nothing to wait for.
                    continue
                timeout = speech.wav_duration(synthesis.wav) + self.ended_grace
                try:
                    await asyncio.wait_for(future, timeout)
                except asyncio.TimeoutError:
                    log.warning("no speak_ended for %d within %.1fs, moving on", id, timeout)
            finally:
                del self.pending[id]
        stage = self._stage()
        if faced and stage is not None:
            await self._send(stage, protocol.expression("neutral"))

    async def _play_motion(self, name):
        stage = self._stage()
        if stage is None:
            log.info("no stage, skipped motion %s", name)
            return
        if self.state != "speaking":
            await self._set_state("speaking")
        future = asyncio.get_running_loop().create_future()
        self.motions[name] = future
        try:
            await self._send(stage, protocol.motion(name))
            if stage not in self.connections:
                return
            try:
                await asyncio.wait_for(future, self.motion_timeout)
            except asyncio.TimeoutError:
                log.warning("no motion_ended for %s within %.0fs, moving on", name, self.motion_timeout)
        finally:
            del self.motions[name]
